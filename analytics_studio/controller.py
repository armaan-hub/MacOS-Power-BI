"""Python state and project lifecycle exposed to the Qt Quick interface."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import calendar
import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, DecimalException
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QSettings,
    Signal,
    Slot,
    QTimer,
)
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox

from analytics_studio.project import (
    ProjectFileError,
    load_project,
    new_project,
    resolve_source_path,
    save_project,
    source_path_for_save,
    validate_project,
)
from analytics_studio.data_sources import DATA_SOURCE_CATALOG
from analytics_studio.file_import import FileImportError, ImportCandidate, kind_for_path, parse_file
from analytics_studio.folder_import import parse_folder
from analytics_studio.folder_import_dialog import FolderImportDialog
from analytics_studio.inline_data import sample_candidate, source_from_candidate
from analytics_studio.date_table_dialog import DateTableDialog
from analytics_studio.date_tables import DateTableError, validate_date_table_rows
from analytics_studio.calendar_table_dialog import CalendarTableDialog
from analytics_studio.calendar_tables import (
    calendar_expression,
    generate_calendar,
    generate_calendar_auto,
)
from analytics_studio.local_table_dialogs import (
    AppendQueriesDialog,
    CalculatedTableDialog,
    EnterDataDialog,
    MergeQueriesDialog,
    TransformDataDialog,
)
from analytics_studio.measure_dialog import MeasureDialog
from analytics_studio.calculated_column_dialog import CalculatedColumnDialog
from analytics_studio.measures import (
    MAX_MEASURES,
    MeasureError,
    evaluate_calculated_table,
    evaluate_calculated_columns,
    evaluate_measures,
    normalize_measure,
    validate_calculated_columns,
)
from analytics_studio.query_engine import QueryError, append_candidates, merge_candidates
from analytics_studio.recent_sources import RecentSourcesStore
from analytics_studio.sql_server import SQLServerError, read_sql_server_object
from analytics_studio.sql_server_credentials import (
    CredentialStoreError,
    delete_password as delete_sql_server_password,
    get_password as get_sql_server_password,
    set_password as set_sql_server_password,
)
from analytics_studio.sql_server_dialog import SQLServerImportDialog
from analytics_studio.odata import ODataError, read_odata_entity_set
from analytics_studio.odata_dialog import ODataFeedImportDialog
from analytics_studio.relationship_dialog import RelationshipDialog
from analytics_studio.relationships import (
    RELATIONSHIP_VERSION,
    RelationshipError,
    normalize_relationships,
    propagate_relationship_filters,
)
from analytics_studio.web_import import read_web_source
from analytics_studio.web_import_dialog import WebImportDialog
from analytics_studio.transformations import (
    SUPPORTED_COLUMN_TYPES,
    TransformationError,
    apply_transformations,
    column_types_after_steps,
    count_conversion_errors,
    validate_steps,
)


PREVIEW_ROW_LIMIT = 500
CHART_TYPES = {"column", "bar", "line"}
CHART_VISUALS = {"Monthly revenue", "Region revenue"}
SUPPORTED_SOURCE_KINDS = {"csv", "excel", "json", "xml", "parquet", "sqlite", "folder", "query", "sql_server", "odata", "web"}
PATHLESS_SOURCE_KINDS = {"inline", "query", "sql_server", "odata", "web"}
_REPORT_FIELD_ALIASES = {
    "revenue": ("revenue", "sales", "net sales", "sales amount", "sales value", "value", "gross total", "amount", "invoice total", "total sales"),
    "cost": ("cost", "total cost", "cogs", "cost amount"),
    "margin": ("margin", "profit", "gross profit", "gross margin"),
    "units": ("units", "quantity", "qty"),
    "date": ("order date", "invoice date", "transaction date", "posting date", "date"),
    "region": ("region", "emirates", "emirate", "state", "province", "country", "city", "location"),
}
_REPORT_FILTER_OPERATOR_LABELS = {
    "equals": "is",
    "not_equals": "is not",
    "is_any_of": "is any of",
    "is_none_of": "is none of",
    "relative_date": "relative date",
    "relative_time": "relative time",
    "top_n": "Top N",
    "contains": "contains",
    "does_not_contain": "does not contain",
    "begins_with": "begins with",
    "does_not_begin_with": "does not begin with",
    "ends_with": "ends with",
    "does_not_end_with": "does not end with",
    "greater_than": "is greater than",
    "greater_than_or_equal": "is greater than or equal to",
    "less_than": "is less than",
    "less_than_or_equal": "is less than or equal to",
    "is_blank": "is blank",
    "is_not_blank": "is not blank",
}
_REPORT_FILTER_VALUELESS = {"is_blank", "is_not_blank"}
_REPORT_FILTER_MULTI_VALUE = {"is_any_of", "is_none_of"}
_REPORT_FILTER_RELATIVE_DATE = "relative_date"
_REPORT_FILTER_RELATIVE_TIME = "relative_time"
_REPORT_FILTER_TOP_N = "top_n"
_REPORT_FILTER_RELATIVE_DATE_UNITS = {
    "days", "weeks", "calendar_weeks", "months", "calendar_months",
    "years", "calendar_years",
}
_REPORT_FILTER_RELATIVE_TIME_UNITS = {"minutes", "hours"}
_REPORT_FILTER_REQUIRED_VALUE = {
    "contains", "does_not_contain", "begins_with", "does_not_begin_with",
    "ends_with", "does_not_end_with", "greater_than", "greater_than_or_equal",
    "less_than", "less_than_or_equal",
}
_REPORT_FILTER_NUMERIC_TYPES = {"whole_number", "decimal_number"}
_REPORT_FILTER_TEMPORAL_TYPES = {"date", "datetime", "time"}
_REPORT_FILTER_NUMERIC_OPERATORS = {
    "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
}


def _report_filter_operators(column_type: str) -> list[str]:
    common = ["equals", "not_equals", "is_any_of", "is_none_of", "is_blank", "is_not_blank"]
    if column_type == "date":
        return [
            "equals", "not_equals", "is_any_of", "is_none_of", "relative_date",
            "greater_than", "greater_than_or_equal",
            "less_than", "less_than_or_equal", "is_blank", "is_not_blank",
        ]
    if column_type == "datetime":
        return [
            "equals", "not_equals", "is_any_of", "is_none_of", "relative_time",
            "greater_than", "greater_than_or_equal",
            "less_than", "less_than_or_equal", "is_blank", "is_not_blank",
        ]
    if column_type in _REPORT_FILTER_NUMERIC_TYPES | _REPORT_FILTER_TEMPORAL_TYPES:
        return [
            "equals", "not_equals", "is_any_of", "is_none_of",
            "greater_than", "greater_than_or_equal",
            "less_than", "less_than_or_equal", "is_blank", "is_not_blank",
        ]
    if column_type == "boolean":
        return common
    return [
        "equals", "not_equals", "is_any_of", "is_none_of",
        "contains", "does_not_contain", "begins_with",
        "does_not_begin_with", "ends_with", "does_not_end_with", "is_blank",
        "is_not_blank",
    ]


def _report_filter_has_relative_date(report_filter: dict[str, Any]) -> bool:
    return any(
        clause.get("operator") == _REPORT_FILTER_RELATIVE_DATE
        for clause in report_filter.get("clauses", [])
    )


def _report_filter_has_relative_time(report_filter: dict[str, Any]) -> bool:
    return any(
        clause.get("operator") == _REPORT_FILTER_RELATIVE_TIME
        for clause in report_filter.get("clauses", [])
    )


def _parse_report_filter_value(value: str, column_type: str) -> Decimal | date | datetime | time | str:
    if column_type in _REPORT_FILTER_NUMERIC_TYPES:
        parsed_number = Decimal(value)
        if not parsed_number.is_finite() or (
            column_type == "whole_number"
            and parsed_number != parsed_number.to_integral_value()
        ):
            raise ValueError("Enter a finite value that matches the field's number type.")
        return parsed_number
    if column_type == "date":
        return date.fromisoformat(value)
    if column_type == "datetime":
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if column_type == "time":
        return time.fromisoformat(value)
    return value


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _shift_years(value: date, years: int) -> date:
    year = value.year + years
    return date(year, value.month, min(value.day, calendar.monthrange(year, value.month)[1]))


def _relative_period_start(anchor: date, unit: str) -> date:
    if unit == "days":
        return anchor
    if unit == "weeks":
        return anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    if unit == "months":
        return anchor.replace(day=1)
    if unit == "years":
        return anchor.replace(month=1, day=1)
    raise ValueError("Unsupported relative-date unit.")


def _shift_relative_period(value: date, unit: str, count: int) -> date:
    if unit in {"days", "weeks"}:
        return value + timedelta(days=count * (7 if unit == "weeks" else 1))
    if unit == "months":
        return _shift_months(value, count)
    if unit == "years":
        return _shift_years(value, count)
    raise ValueError("Unsupported relative-date unit.")


def _relative_date_bounds(rule: dict[str, Any], anchor: date) -> tuple[date, date]:
    direction = rule["direction"]
    count = rule["count"]
    unit = rule["unit"]
    calendar_unit = unit.startswith("calendar_")
    base_unit = unit.removeprefix("calendar_")
    current_period_start = _relative_period_start(anchor, base_unit)

    if direction == "this":
        if base_unit == "days":
            return anchor, anchor
        end = _shift_relative_period(current_period_start, base_unit, 1) - timedelta(days=1)
        return current_period_start, end

    if calendar_unit:
        if direction == "last":
            end = current_period_start - timedelta(days=1)
            start = _shift_relative_period(current_period_start, base_unit, -count)
        else:
            start = _shift_relative_period(current_period_start, base_unit, 1)
            end = _shift_relative_period(start, base_unit, count) - timedelta(days=1)
        return start, end

    if direction == "last":
        end = anchor if rule["include_today"] else anchor - timedelta(days=1)
        if base_unit == "days":
            start = end - timedelta(days=count - 1)
        elif base_unit == "weeks":
            start = end - timedelta(days=(count * 7) - 1)
        elif base_unit == "months":
            start = _shift_months(end, -count) + timedelta(days=1)
        else:
            start = _shift_years(end, -count) + timedelta(days=1)
        return start, end

    start = anchor if rule["include_today"] else anchor + timedelta(days=1)
    if base_unit == "days":
        end = start + timedelta(days=count - 1)
    elif base_unit == "weeks":
        end = start + timedelta(days=(count * 7) - 1)
    elif base_unit == "months":
        end = _shift_months(start, count) - timedelta(days=1)
    else:
        end = _shift_years(start, count) - timedelta(days=1)
    return start, end


def _parse_report_datetime_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _relative_time_bounds(
    rule: dict[str, Any], anchor: datetime
) -> tuple[datetime, datetime, bool]:
    unit = rule["unit"]
    period = timedelta(minutes=1) if unit == "minutes" else timedelta(hours=1)
    if rule["direction"] == "this":
        if unit == "minutes":
            start = anchor.replace(second=0, microsecond=0)
        else:
            start = anchor.replace(minute=0, second=0, microsecond=0)
        return start, start + period, False

    span = period * rule["count"]
    if rule["direction"] == "last":
        return anchor - span, anchor, True
    return anchor, anchor + span, True


def _report_filter_clause_matches(
    raw_value: Any,
    clause: dict[str, Any],
    column_type: str,
) -> bool:
    value = "" if raw_value is None else str(raw_value)
    operator = clause["operator"]
    if operator == _REPORT_FILTER_TOP_N:
        return False
    if operator == _REPORT_FILTER_RELATIVE_DATE:
        if column_type != "date" or clause.get("_invalid_relative_date") or not value:
            return False
        try:
            actual_date = date.fromisoformat(value)
        except (ValueError, TypeError):
            return False
        return clause["_relative_start"] <= actual_date <= clause["_relative_end"]
    if operator == _REPORT_FILTER_RELATIVE_TIME:
        if column_type != "datetime" or clause.get("_invalid_relative_time") or not value:
            return False
        try:
            actual_time = _parse_report_datetime_utc(value)
        except (ValueError, TypeError):
            return False
        return (
            clause["_relative_start"] <= actual_time
            and (
                actual_time < clause["_relative_end"]
                if not clause["_relative_end_inclusive"]
                else actual_time <= clause["_relative_end"]
            )
        )
    if operator in _REPORT_FILTER_MULTI_VALUE:
        if clause.get("_invalid_values"):
            return False
        selected_values = clause.get("_normalized_values")
        if selected_values is None:
            selected_values = frozenset(clause["values"])
        if value == "":
            is_selected = bool(clause.get("_includes_blank", "" in clause.get("values", [])))
        elif column_type in _REPORT_FILTER_NUMERIC_TYPES | _REPORT_FILTER_TEMPORAL_TYPES:
            try:
                actual_value = _parse_report_filter_value(value, column_type)
            except (DecimalException, ValueError, TypeError):
                return False
            is_selected = actual_value in selected_values
        else:
            is_selected = value in selected_values
        return is_selected if operator == "is_any_of" else not is_selected
    expected = clause["value"]
    if operator == "is_blank":
        return value == ""
    if operator == "is_not_blank":
        return value != ""
    typed_comparison = column_type in _REPORT_FILTER_NUMERIC_TYPES | _REPORT_FILTER_TEMPORAL_TYPES
    if value == "" and typed_comparison:
        return False
    if operator == "equals":
        if typed_comparison:
            try:
                return _parse_report_filter_value(value, column_type) == _parse_report_filter_value(
                    expected, column_type
                )
            except (DecimalException, ValueError, TypeError):
                return False
        return value == expected
    if operator == "not_equals":
        if typed_comparison:
            try:
                return _parse_report_filter_value(value, column_type) != _parse_report_filter_value(
                    expected, column_type
                )
            except (DecimalException, ValueError, TypeError):
                return False
        return value != expected
    if operator == "contains":
        return expected in value
    if operator == "does_not_contain":
        return expected not in value
    if operator == "begins_with":
        return value.startswith(expected)
    if operator == "does_not_begin_with":
        return not value.startswith(expected)
    if operator == "ends_with":
        return value.endswith(expected)
    if operator == "does_not_end_with":
        return not value.endswith(expected)
    if operator not in _REPORT_FILTER_NUMERIC_OPERATORS:
        return False
    try:
        actual_value = _parse_report_filter_value(value, column_type)
        expected_value = _parse_report_filter_value(expected, column_type)
        if isinstance(actual_value, str) or isinstance(expected_value, str):
            return False
        if operator == "greater_than":
            return actual_value > expected_value
        if operator == "greater_than_or_equal":
            return actual_value >= expected_value
        if operator == "less_than":
            return actual_value < expected_value
        return actual_value <= expected_value
    except (DecimalException, ValueError, TypeError):
        return False


def _report_filter_matches(
    raw_value: Any,
    report_filter: dict[str, Any],
    column_type: str,
) -> bool:
    results = [
        _report_filter_clause_matches(raw_value, clause, column_type)
        for clause in report_filter["clauses"]
    ]
    return all(results) if report_filter["logic"] == "and" else any(results)


def _compile_report_filter(
    report_filter: dict[str, Any],
    column_type: str,
    anchor_date: date,
    anchor_time: datetime,
) -> dict[str, Any]:
    compiled = deepcopy(report_filter)
    for clause in compiled["clauses"]:
        if clause["operator"] == _REPORT_FILTER_RELATIVE_DATE:
            if column_type != "date":
                clause["_invalid_relative_date"] = True
            else:
                try:
                    clause["_relative_start"], clause["_relative_end"] = (
                        _relative_date_bounds(clause, anchor_date)
                    )
                except (OverflowError, ValueError):
                    clause["_invalid_relative_date"] = True
            continue
        if clause["operator"] == _REPORT_FILTER_RELATIVE_TIME:
            if column_type != "datetime":
                clause["_invalid_relative_time"] = True
            else:
                try:
                    (
                        clause["_relative_start"],
                        clause["_relative_end"],
                        clause["_relative_end_inclusive"],
                    ) = _relative_time_bounds(clause, anchor_time)
                except (OverflowError, ValueError, TypeError):
                    clause["_invalid_relative_time"] = True
            continue
        if clause["operator"] not in _REPORT_FILTER_MULTI_VALUE:
            continue
        values = clause["values"]
        clause["_includes_blank"] = "" in values
        try:
            if column_type in _REPORT_FILTER_NUMERIC_TYPES | _REPORT_FILTER_TEMPORAL_TYPES:
                clause["_normalized_values"] = frozenset(
                    _parse_report_filter_value(value, column_type)
                    for value in values if value != ""
                )
            else:
                clause["_normalized_values"] = frozenset(values)
        except (DecimalException, ValueError, TypeError):
            clause["_invalid_values"] = True
    return compiled


def _report_filter_summary(clauses: list[dict[str, Any]], logic: str) -> str:
    summaries = []
    symbols = {
        "equals": "=", "not_equals": "≠", "greater_than": ">",
        "greater_than_or_equal": "≥", "less_than": "<", "less_than_or_equal": "≤",
    }
    for clause in clauses:
        operator = clause["operator"]
        if operator == _REPORT_FILTER_RELATIVE_DATE:
            unit_names = {
                "days": "day", "weeks": "week", "calendar_weeks": "calendar week",
                "months": "month", "calendar_months": "calendar month",
                "years": "year", "calendar_years": "calendar year",
            }
            direction = clause["direction"]
            unit_name = unit_names[clause["unit"]]
            if direction == "this":
                summaries.append(f"in this {unit_name}")
            else:
                count = clause["count"]
                plural_unit = unit_name if count == 1 else f"{unit_name}s"
                summary = f"in the {direction} {count} {plural_unit}"
                if not clause["unit"].startswith("calendar_"):
                    summary += " including today" if clause["include_today"] else " excluding today"
                summaries.append(summary)
        elif operator == _REPORT_FILTER_RELATIVE_TIME:
            unit_name = "minute" if clause["unit"] == "minutes" else "hour"
            if clause["direction"] == "this":
                summaries.append(f"in this {unit_name}")
            else:
                count = clause["count"]
                plural_unit = unit_name if count == 1 else f"{unit_name}s"
                summaries.append(f"in the {clause['direction']} {count} {plural_unit}")
        elif operator == _REPORT_FILTER_TOP_N:
            order_by = clause.get("order_by", {})
            summaries.append(
                f"{clause['direction'].title()} {clause['count']} by {order_by.get('column', 'value')}"
            )
        elif operator in _REPORT_FILTER_VALUELESS:
            summaries.append(_REPORT_FILTER_OPERATOR_LABELS[operator])
        elif operator in _REPORT_FILTER_MULTI_VALUE:
            values = ["(Blank)" if item == "" else item for item in clause["values"]]
            preview = ", ".join(values[:3])
            if len(values) > 3:
                preview += f", +{len(values) - 3} more"
            summaries.append(f"{_REPORT_FILTER_OPERATOR_LABELS[operator]} {preview}")
        else:
            label = symbols.get(operator, _REPORT_FILTER_OPERATOR_LABELS[operator])
            value = clause["value"] or "(Blank)"
            summaries.append(f"{label} {value}")
    return f" {logic.upper()} ".join(summaries)


def _normalized_header(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _report_field(headers: list[str], role: str) -> str | None:
    by_key = {_normalized_header(header): header for header in headers}
    for alias in _REPORT_FIELD_ALIASES[role]:
        found = by_key.get(_normalized_header(alias))
        if found is not None:
            return found
    return None


def _report_number(value: Any) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    for marker in ("AED", "USD", "EUR", "GBP", "د.إ"):
        text = text.replace(marker, "")
    try:
        number = Decimal(text.replace(",", "").strip())
    except (DecimalException, ValueError):
        return None
    if not number.is_finite():
        return None
    return -number if negative else number


def _report_month(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m")
    except ValueError:
        pass
    for format_string in ("%d-%b-%Y", "%d-%B-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, format_string).strftime("%Y-%m")
        except ValueError:
            continue
    return None


def _format_report_number(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"


def _require_unique_relationship_values(
    rows: list[dict[str, Any]],
    column: str,
    table_name: str,
    column_type: str,
) -> None:
    seen: set[Any] = set()
    for row in rows:
        value = "" if row.get(column) is None else str(row.get(column, ""))
        if column_type in {"whole_number", "decimal_number"} and value != "":
            try:
                number = Decimal(value)
            except DecimalException as exc:
                raise RelationshipError(
                    f"{table_name}[{column}] contains a value that is not a valid number."
                ) from exc
            if not number.is_finite() or (
                column_type == "whole_number"
                and number != number.to_integral_value()
            ):
                raise RelationshipError(
                    f"{table_name}[{column}] contains a value that is not a valid "
                    f"{column_type.replace('_', ' ')}."
                )
            key: Any = ("number", number)
        else:
            key = ("value", value)
        if key in seen:
            raise RelationshipError(
                f"{table_name}[{column}] must contain unique values, including blanks, "
                "when selected as the one side. Remove duplicates, change cardinality, "
                "or reverse the relationship direction."
            )
        seen.add(key)


def _web_table_name(url: str, options: dict[str, Any]) -> str:
    resource_type = options.get("resource_type")
    if resource_type == "html_table":
        return f"Web Table {options.get('table_index', 0) + 1}"
    if resource_type == "json":
        path = options.get("json_path", [])
        if path:
            return str(path[-1]) if isinstance(path[-1], str) else f"Web Table {path[-1] + 1}"
        return "Web Data"
    leaf = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    stem = Path(leaf).stem.strip()
    return stem or f"Web {str(resource_type or 'data').title()}"


class CsvTableModel(QAbstractTableModel):
    """Read-only CSV preview model, limited to the first 500 records."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[dict[str, str | None]] = []

    def replace_data(self, headers: list[str], rows: list[dict[str, str | None]]) -> None:
        self.beginResetModel()
        self._headers = list(headers)
        self._rows = list(rows[:PREVIEW_ROW_LIMIT])
        self.endResetModel()

    def clear(self) -> None:
        self.replace_data([], [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 (Qt API)
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 (Qt API)
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.row() >= len(self._rows) or index.column() >= len(self._headers):
            return None
        value = self._rows[index.row()].get(self._headers[index.column()], "")
        return "" if value is None else str(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:  # noqa: N802 (Qt API)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802 (Qt API)
        # Qt Quick TableView delegates can read the standard display role by name.
        return {int(Qt.ItemDataRole.DisplayRole): b"display"}


class StudioController(QObject):
    """Owns application state and exposes deliberate, synchronous QML APIs."""

    stateChanged = Signal()
    statusChanged = Signal(str)

    def __init__(self, parent: QObject | None = None, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self._project = new_project()
        self._project_path: Path | None = None
        self._recovered_from_backup = False
        self._dirty = False
        self._current_view = "Report"
        self._active_page_id = self._project["report"]["active_page_id"]
        self._headers: list[str] = []
        self._rows: list[dict[str, str | None]] = []
        self._source_path: Path | None = None
        self._source_id: str | None = None
        self._active_source_id: str | None = None
        self._active_source_path: Path | None = None
        self._active_source_kind: str | None = None
        self._active_parser_options: dict[str, Any] = {}
        self._loaded_candidates: dict[str, ImportCandidate] = {}
        self._source_load_errors: dict[str, str] = {}
        self._sql_server_passwords: dict[str, str] = {}
        self._source_warning = ""
        self._field_query = ""
        self._current_region: str | None = None
        self._selected_visual = ""
        self._status_message = "Ready · new project"
        self._kpis: dict[str, str] = {}
        self._region_column: str | None = None
        self._measure_values: dict[str, str] = {}
        self._measure_errors: dict[str, str] = {}
        self._visual_kpis: dict[str, str] = {}
        self._filter_context_error = ""
        relative_filter_now = datetime.now(timezone.utc)
        self._relative_filter_anchor_date = relative_filter_now.date()
        self._relative_filter_anchor_time = relative_filter_now
        self._relative_filter_timer = QTimer(self)
        self._relative_filter_timer.setSingleShot(True)
        self._relative_filter_timer.timeout.connect(self._on_relative_filter_boundary)
        self._monthly_chart_message = "No date and numeric sales field found in this source."
        self._region_chart_message = "No region and numeric sales field found in this source."
        self._monthly_series: list[dict[str, str | float]] = []
        self._region_series: list[dict[str, str | float]] = []
        self._monthly_visual_series: dict[str, list[dict[str, str | float]]] = {}
        self._region_visual_series: dict[str, list[dict[str, str | float]]] = {}
        self._model_tables: list[str] = []
        self._table_catalog: list[dict[str, Any]] = []
        self._model_relationships: list[str] = []
        self._recent_source_store = RecentSourcesStore(settings)
        self._table_model = CsvTableModel(self)
        self._refresh_model_view()
        self._refresh_report()

    # QML-facing state. The dictionaries/lists are returned as fresh QVariant values.
    @Property(str, notify=stateChanged)
    def windowTitle(self) -> str:  # noqa: N802
        suffix = " *" if self._dirty else ""
        return f"Analytics Studio — {self._project.get('name', 'Untitled Project')}{suffix}"

    @Property(str, notify=stateChanged)
    def projectName(self) -> str:  # noqa: N802
        return str(self._project.get("name", "Untitled Project"))

    @Property(str, notify=stateChanged)
    def projectPathLabel(self) -> str:  # noqa: N802
        return self._project_path.name if self._project_path else "Unsaved project"

    @Property(bool, notify=stateChanged)
    def dirty(self) -> bool:
        return self._dirty

    @Property(str, notify=stateChanged)
    def currentView(self) -> str:  # noqa: N802
        return self._current_view

    @Property("QVariantList", notify=stateChanged)
    def pages(self) -> list[dict[str, str]]:
        return [
            {"id": str(page["id"]), "name": str(page["name"]), "hidden": bool(page.get("hidden", False))}
            for page in self._project["report"]["pages"]
        ]

    @Property("QVariantList", constant=True)
    def dataSourceCatalog(self) -> list[dict[str, object]]:  # noqa: N802
        """Return category-specific source rows for the UI-only picker catalog."""
        return [dict(item) for item in DATA_SOURCE_CATALOG]

    @Property(int, notify=stateChanged)
    def activePageIndex(self) -> int:  # noqa: N802
        pages = self._project["report"]["pages"]
        return next(
            (index for index, page in enumerate(pages) if page["id"] == self._active_page_id),
            0,
        )

    @Property(str, notify=stateChanged)
    def activePageName(self) -> str:  # noqa: N802
        pages = self._project["report"]["pages"]
        index = self.activePageIndex
        return str(pages[index]["name"]) if pages else ""

    @Property("QVariantList", notify=stateChanged)
    def activePageVisuals(self) -> list[str]:  # noqa: N802
        pages = self._project["report"]["pages"]
        index = self.activePageIndex
        if not pages:
            return []
        visuals = pages[index].get("visuals", [])
        return [str(v.get("title", "")) if isinstance(v, dict) else str(v) for v in visuals]

    @Property("QVariantList", notify=stateChanged)
    def activeVisualWells(self) -> list[dict[str, object]]:  # noqa: N802
        if not self._selected_visual:
            return []
        pages = self._project["report"]["pages"]
        index = self.activePageIndex
        page = pages[index]
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == self._selected_visual), None)
        if not visual:
            return []
            
        v_type = visual.get("type", "card")
        if v_type in {"column", "bar", "line", "area"}:
            wells = ["X-axis", "Y-axis", "Legend", "Tooltips"]
        elif v_type in {"shape", "text_box", "image"}:
            return []
        else:
            wells = ["Fields", "Tooltips"]
            
        assigned_fields = visual.get("fields", {})
        return [
            {"name": well, "fields": assigned_fields.get(well, [])}
            for well in wells
        ]

    @Property("QVariantList", notify=stateChanged)
    def activeVisualPropertyGroups(self) -> list[dict[str, object]]:  # noqa: N802
        if not self._selected_visual:
            return []
        page = self._active_page()
        if not page:
            return []
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == self._selected_visual), None)
        if not visual:
            return []
            
        return [
            {
                "name": "General",
                "properties": [
                    {"key": "title", "label": "Title Text", "type": "string", "value": visual.get("title", "")},
                    {"key": "x", "label": "X Position", "type": "number", "value": visual.get("x", 10)},
                    {"key": "y", "label": "Y Position", "type": "number", "value": visual.get("y", 10)},
                    {"key": "width", "label": "Width", "type": "number", "value": visual.get("width", 300)},
                    {"key": "height", "label": "Height", "type": "number", "value": visual.get("height", 200)},
                ]
            },
            {
                "name": "Data Colors",
                "properties": [
                    {"key": "color", "label": "Primary Color", "type": "color", "value": visual.get("color", "#0078D4")}
                ]
            }
        ]

    @Property("QVariantList", notify=stateChanged)
    def activeVisualObjects(self) -> list[dict[str, object]]:  # noqa: N802
        pages = self._project["report"]["pages"]
        index = self.activePageIndex
        return list(pages[index].get("visuals", [])) if pages else []

    def _active_page(self) -> dict[str, Any] | None:
        return next(
            (page for page in self._project["report"]["pages"]
             if page.get("id") == self._active_page_id),
            None,
        )

    @Property(str, notify=stateChanged)
    def sourceName(self) -> str:  # noqa: N802
        if self._source_path:
            return self._source_path.name
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == self._active_source_id),
            None,
        )
        return str(source.get("name", "")) if source else ""

    @Property(str, notify=stateChanged)
    def sourceIconName(self) -> str:  # noqa: N802
        return "table" if self._active_source_kind in {"inline", "query", "sql_server", "odata", "web"} else (self._active_source_kind or "csv")

    @Property(bool, notify=stateChanged)
    def sourceLoaded(self) -> bool:  # noqa: N802
        return self._source_id is not None

    @Property(bool, notify=stateChanged)
    def canRefreshSource(self) -> bool:  # noqa: N802
        return (
            self.sourceLoaded
            and not self.activeSourceExcludedFromRefresh
            and (
                self._active_source_kind in {"query", "sql_server", "odata", "web"}
                or (
                    self._active_source_path is not None
                    and self._active_source_kind in SUPPORTED_SOURCE_KINDS
                )
            )
        )

    @Property(bool, notify=stateChanged)
    def canRefreshAllSources(self) -> bool:  # noqa: N802
        return any(
            self._source_is_refresh_root(source)
            for source in self._project.get("data_sources", [])
        )

    @Property(bool, notify=stateChanged)
    def activeSourceExcludedFromRefresh(self) -> bool:  # noqa: N802
        if self._active_source_id is None:
            return False
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == self._active_source_id),
            None,
        )
        return source is not None and not self._source_refresh_included(source)

    @Property("QVariantList", notify=stateChanged)
    def recentSources(self) -> list[dict[str, Any]]:  # noqa: N802
        return [
            {
                "path": item.path,
                "name": item.display_name,
                "kind": item.kind,
                "exists": item.exists,
            }
            for item in self._recent_source_store.sources
        ]

    @Property(str, notify=stateChanged)
    def sourceWarning(self) -> str:  # noqa: N802
        return self._source_warning

    @Property(int, notify=stateChanged)
    def rowCount(self) -> int:  # noqa: N802
        return len(self._rows)

    @Property(int, notify=stateChanged)
    def columnCount(self) -> int:  # noqa: N802
        return len(self._headers)

    @Property("QVariantList", notify=stateChanged)
    def headers(self) -> list[str]:
        return list(self._headers)

    @Property("QVariantList", notify=stateChanged)
    def columnTypes(self) -> list[dict[str, str]]:  # noqa: N802
        type_map = self._active_column_type_map()
        return [
            {"column": header, "type": type_map.get(header, "text")}
            for header in self._headers
        ]

    @Property(QObject, notify=stateChanged)
    def dataModel(self) -> QObject:  # noqa: N802
        return self._table_model

    @Property("QVariantList", notify=stateChanged)
    def fieldNames(self) -> list[str]:  # noqa: N802
        return list(self._headers)

    @Property("QVariantList", notify=stateChanged)
    def filteredFields(self) -> list[str]:  # noqa: N802
        query = self._field_query.casefold()
        return [field for field in self._headers if query in field.casefold()]

    @Property("QVariantMap", notify=stateChanged)
    def reportKpis(self) -> dict[str, str]:  # noqa: N802
        return dict(self._kpis)

    @Property("QVariantMap", notify=stateChanged)
    def visualKpis(self) -> dict[str, str]:  # noqa: N802
        return dict(self._visual_kpis)

    @Property("QVariantList", notify=stateChanged)
    def reportKpiNames(self) -> list[str]:  # noqa: N802
        return ["Revenue", "Cost", "Margin", "Units", "Orders", *self._measure_values]

    @Property("QVariantList", notify=stateChanged)
    def monthlySeries(self) -> list[dict[str, str | float]]:  # noqa: N802
        return [dict(item) for item in self._monthly_series]

    @Property("QVariantList", notify=stateChanged)
    def regionSeries(self) -> list[dict[str, str | float]]:  # noqa: N802
        return [dict(item) for item in self._region_series]

    @Slot(str, result="QVariantList")
    def monthlySeriesForVisual(self, visual_name: str) -> list[dict[str, str | float]]:  # noqa: N802
        series = self._monthly_visual_series.get(visual_name, self._monthly_series)
        return [dict(item) for item in series]

    @Slot(str, result="QVariantList")
    def regionSeriesForVisual(self, visual_name: str) -> list[dict[str, str | float]]:  # noqa: N802
        series = self._region_visual_series.get(visual_name, self._region_series)
        return [dict(item) for item in series]

    @Slot(str, result="QVariantList")
    def visualSeries(self, visual_name: str) -> list[dict[str, str | float]]:
        series = self._generate_dynamic_visual_series(visual_name)
        return [dict(item) for item in series]

    @Property(str, notify=stateChanged)
    def monthlyChartMessage(self) -> str:  # noqa: N802
        return self._monthly_chart_message

    @Property(str, notify=stateChanged)
    def regionChartMessage(self) -> str:  # noqa: N802
        return self._region_chart_message

    @Property(str, notify=stateChanged)
    def monthlyChartType(self) -> str:  # noqa: N802
        return str(self._project["report"]["chart_types"]["monthly"])

    @Property(str, notify=stateChanged)
    def regionChartType(self) -> str:  # noqa: N802
        return str(self._project["report"]["chart_types"]["region"])

    @Property(str, notify=stateChanged)
    def selectedVisual(self) -> str:  # noqa: N802
        return self._selected_visual

    @Property(str, notify=stateChanged)
    def selectedChartType(self) -> str:  # noqa: N802
        key = self._chart_key(self._selected_visual)
        return str(self._project["report"]["chart_types"].get(key, "")) if key else ""

    @Property("QVariantList", notify=stateChanged)
    def regions(self) -> list[str]:
        column = self._region_column
        values = sorted({str(row.get(column, "")) for row in self._rows if column and row.get(column)})
        return ["All regions", *values]

    @Property(str, notify=stateChanged)
    def currentRegion(self) -> str:  # noqa: N802
        return self._current_region or "All regions"

    @Property(bool, notify=stateChanged)
    def filterActive(self) -> bool:  # noqa: N802
        page = self._active_page()
        return (
            self._current_region is not None
            or bool(self._project.get("report", {}).get("filters"))
            or bool(page and (page.get("filters") or page.get("visual_filters")))
        )

    @Property(str, notify=stateChanged)
    def filterContextError(self) -> str:  # noqa: N802
        return self._filter_context_error

    @Property("QVariantList", notify=stateChanged)
    def pageFilterFields(self) -> list[dict[str, str]]:  # noqa: N802
        fields: list[dict[str, str]] = []
        for table in self._table_catalog:
            if not (table.get("loaded") and table.get("loadEnabled")):
                continue
            table_id = str(table.get("id", ""))
            for column in table.get("headers", []):
                column_name = str(column)
                fields.append({
                    "tableId": table_id,
                    "column": column_name,
                    "columnType": str(table.get("columnTypes", {}).get(column_name, "text")),
                    "label": f"{table.get('displayName', table.get('name', table_id))} · {column_name}",
                })
        return fields

    @Property("QVariantList", notify=stateChanged)
    def activeReportFilters(self) -> list[dict[str, str]]:  # noqa: N802
        report = self._project.get("report", {})
        tables = {str(table.get("id", "")): table for table in self._table_catalog}
        result = []
        for index, report_filter in enumerate(report.get("filters", [])):
            table_id = str(report_filter["table_id"])
            column = str(report_filter["column"])
            display_value = _report_filter_summary(
                report_filter["clauses"], report_filter["logic"]
            )
            table = tables.get(table_id, {})
            result.append({
                "index": str(index),
                "tableId": table_id,
                "tableName": str(table.get("displayName") or table.get("name") or table_id),
                "column": column,
                "displayValue": display_value,
            })
        return result

    @Property("QVariantList", notify=stateChanged)
    def activePageFilters(self) -> list[dict[str, str]]:  # noqa: N802
        page = self._active_page()
        if page is None:
            return []
        tables = {str(table.get("id", "")): table for table in self._table_catalog}
        result = []
        for index, page_filter in enumerate(page.get("filters", [])):
            table_id = str(page_filter["table_id"])
            column = str(page_filter["column"])
            display_value = _report_filter_summary(
                page_filter["clauses"], page_filter["logic"]
            )
            table = tables.get(table_id, {})
            result.append({
                "index": str(index),
                "tableId": table_id,
                "tableName": str(table.get("displayName") or table.get("name") or table_id),
                "column": column,
                "displayValue": display_value,
            })
        return result

    @Property("QVariantList", notify=stateChanged)
    def activeVisualFilters(self) -> list[dict[str, str]]:  # noqa: N802
        page = self._active_page()
        if page is None or not self._selected_visual:
            return []
        tables = {str(table.get("id", "")): table for table in self._table_catalog}
        result = []
        for index, visual_filter in enumerate(page.get("visual_filters", [])):
            if visual_filter["visual_name"] != self._selected_visual:
                continue
            table_id = str(visual_filter["table_id"])
            column = str(visual_filter["column"])
            display_value = _report_filter_summary(
                visual_filter["clauses"], visual_filter["logic"]
            )
            table = tables.get(table_id, {})
            result.append({
                "index": str(index),
                "visualName": self._selected_visual,
                "tableId": table_id,
                "tableName": str(table.get("displayName") or table.get("name") or table_id),
                "column": column,
                "displayValue": display_value,
            })
        return result

    @Property("QVariantList", notify=stateChanged)
    def modelTables(self) -> list[str]:  # noqa: N802
        return list(self._model_tables)

    @Property("QVariantList", notify=stateChanged)
    def tableCatalog(self) -> list[dict[str, Any]]:  # noqa: N802
        return [dict(table) for table in self._table_catalog]

    @Slot(str, str, result="QVariantList")
    def pageFilterValues(self, table_id: str, column: str) -> list[dict[str, str]]:  # noqa: N802
        table = next(
            (item for item in self._table_catalog
             if item.get("id") == table_id and item.get("loaded") and item.get("loadEnabled")),
            None,
        )
        source_id = str(table.get("sourceId", "")) if table else ""
        candidate = self._loaded_candidates.get(source_id)
        if candidate is None or column not in candidate.headers:
            return []
        distinct = {"" if row.get(column) is None else str(row.get(column, "")) for row in candidate.rows}
        ordered = sorted(distinct, key=lambda value: (value.casefold(), value))[:1000]
        return [
            {"label": value if value else "(Blank)", "value": value}
            for value in ordered
        ]

    @Slot(str, str, str, result="QVariantList")
    def searchPageFilterValues(  # noqa: N802
        self, table_id: str, column: str, search: str
    ) -> list[dict[str, str]]:
        table = next(
            (item for item in self._table_catalog
             if item.get("id") == table_id and item.get("loaded") and item.get("loadEnabled")),
            None,
        )
        source_id = str(table.get("sourceId", "")) if table else ""
        candidate = self._loaded_candidates.get(source_id)
        if candidate is None or column not in candidate.headers:
            return []
        query = (search or "").strip().casefold()
        distinct = {
            "" if row.get(column) is None else str(row.get(column, ""))
            for row in candidate.rows
        }
        ordered = sorted(
            (
                value for value in distinct
                if not query or query in (value if value else "(blank)").casefold()
            ),
            key=lambda value: (value.casefold(), value),
        )[:200]
        return [
            {"label": value if value else "(Blank)", "value": value}
            for value in ordered
        ]

    @Slot(str, result="QVariantList")
    def pageFilterOperators(self, column_type: str) -> list[dict[str, str]]:  # noqa: N802
        return [
            {"value": operator, "label": _REPORT_FILTER_OPERATOR_LABELS[operator]}
            for operator in _report_filter_operators(column_type)
        ]

    @Slot(str, str, str, str, result="QVariantList")
    def visualFilterOperators(
        self, table_id: str, column: str, column_type: str, visual_name: str
    ) -> list[dict[str, str]]:  # noqa: N802
        operators = self.pageFilterOperators(column_type)
        active_table_id = self._active_model_table_id()
        region_column = _report_field(self._headers, "region") if self.sourceLoaded else None
        if (
            visual_name == "Region revenue"
            and table_id == active_table_id
            and column == region_column
        ):
            operators.append({"value": _REPORT_FILTER_TOP_N, "label": "Top N"})
        return operators

    @Property("QVariantList", notify=stateChanged)
    def topNOrderByFields(self) -> list[dict[str, str]]:  # noqa: N802
        table_id = self._active_model_table_id()
        table = next((item for item in self._table_catalog if item.get("id") == table_id), None)
        candidate = self._loaded_candidates.get(str(table.get("sourceId", ""))) if table else None
        if candidate is None:
            return []
        type_map = table.get("columnTypes", {})
        semantic_numeric = {
            _report_field(candidate.headers, role)
            for role in ("revenue", "cost", "margin", "units")
        }
        return [
            {
                "column": str(column),
                "label": str(column),
            }
            for column in candidate.headers
            if column != _report_field(candidate.headers, "region")
            and (
                str(type_map.get(column, "text")) in _REPORT_FILTER_NUMERIC_TYPES
                or column in semantic_numeric
            )
        ]

    @Slot(str, str, result=bool)
    def setColumnType(self, column: str, type_name: str) -> bool:  # noqa: N802
        """Validate, normalize, and persist a type change for one active column."""
        if not self.sourceLoaded or self._active_source_id is None:
            self._set_status("Load a table before changing a column type.")
            return False
        if column not in self._headers:
            self._set_status("Choose a column from the active table.")
            return False
        if type_name not in SUPPORTED_COLUMN_TYPES:
            self._set_status("That column type is not supported.")
            return False
        if self._active_column_type_map().get(column, "text") == type_name:
            self._set_status(f"{column} is already set to {type_name.replace('_', ' ')}")
            return True
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == self._active_source_id),
            None,
        )
        if source is None:
            self._set_status("The active table has no data source record.")
            return False
        try:
            raw_candidate = self._raw_candidate_for_source(source)
            existing_steps = list(source.get("transform_steps", []))
            new_type_step = {"op": "convert_type", "column": column, "type": type_name}
            if (
                existing_steps
                and existing_steps[-1].get("op") == "convert_type"
                and existing_steps[-1].get("column") == column
            ):
                existing_steps[-1] = new_type_step
            else:
                existing_steps.append(new_type_step)
            steps = validate_steps(existing_steps)
            transformed = apply_transformations(raw_candidate, steps)
        except (OSError, ProjectFileError, TypeError, ValueError) as exc:
            self._set_status(f"Could not set {column} to {type_name.replace('_', ' ')}: {exc}")
            return False
        return self._commit_transform_steps(
            self._active_source_id,
            steps,
            transformed,
            previewed_source=raw_candidate,
        )

    @Slot(str, result="QVariantMap")
    def profileColumn(self, column: str) -> dict[str, Any]:  # noqa: N802
        """Summarize quality and value distribution for one active table column."""
        if not self.sourceLoaded or column not in self._headers:
            return {}
        values = [
            "" if row.get(column) is None else str(row.get(column, ""))
            for row in self._rows
        ]
        non_empty = [value for value in values if value != ""]
        frequencies: dict[str, int] = {}
        for value in non_empty:
            frequencies[value] = frequencies.get(value, 0) + 1
        type_name = self._active_column_type_map().get(column, "text")
        errors = count_conversion_errors(non_empty, type_name) if type_name != "text" else 0
        valid_count = len(non_empty) - errors
        row_count = len(values)
        top_values = sorted(
            frequencies.items(),
            key=lambda item: (-item[1], item[0].casefold(), item[0]),
        )[:5]
        return {
            "column": column,
            "type": type_name,
            "rowCount": row_count,
            "validCount": valid_count,
            "errorCount": errors,
            "emptyCount": row_count - len(non_empty),
            "validPercent": round(valid_count * 100 / row_count) if row_count else 0,
            "errorPercent": round(errors * 100 / row_count) if row_count else 0,
            "emptyPercent": (
                round((row_count - len(non_empty)) * 100 / row_count)
                if row_count else 0
            ),
            "distinctCount": len(frequencies),
            "uniqueCount": sum(1 for count in frequencies.values() if count == 1),
            "topValues": [
                {"value": value, "count": count}
                for value, count in top_values
            ],
        }

    @Property(str, notify=stateChanged)
    def activeTableId(self) -> str:  # noqa: N802
        return self._active_source_id or ""

    @Property(int, notify=stateChanged)
    def activeTableIndex(self) -> int:  # noqa: N802
        return next(
            (index for index, table in enumerate(self._table_catalog)
             if table.get("sourceId") == self._active_source_id),
            -1,
        )

    @Property("QVariantList", notify=stateChanged)
    def modelRelationships(self) -> list[str]:  # noqa: N802
        return list(self._model_relationships)

    @Property(bool, notify=stateChanged)
    def canManageRelationships(self) -> bool:  # noqa: N802
        has_two_loaded_tables = sum(
            1 for table in self._table_catalog
            if table.get("loaded") and table.get("loadEnabled") and table.get("headers")
        ) >= 2
        return has_two_loaded_tables or bool(
            self._project.get("model", {}).get("relationships", [])
        )

    @Property("QVariantList", notify=stateChanged)
    def modelMeasures(self) -> list[dict[str, str]]:  # noqa: N802
        measures = self._project.get("model", {}).get("measures", [])
        result = []
        for measure in measures:
            name = str(measure["name"])
            result.append({
                "name": name,
                "expression": str(measure["expression"]),
                "value": self._measure_values.get(name, "—"),
                "error": self._measure_errors.get(name, ""),
            })
        return result

    @Property(bool, notify=stateChanged)
    def formatPainterActive(self) -> bool:  # noqa: N802
        return self._format_painter_active

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:  # noqa: N802
        return self._status_message

    # Command entry point shared by the ribbon, menu and keyboard shortcuts.
    @Slot(str)
    def executeCommand(self, command_id: str) -> None:  # noqa: N802
        commands = {
            "newProject": self.new_project_dialog,
            "openProject": self.open_project_dialog,
            "saveProject": self.save_current_project,
            "saveProjectAs": self.save_project_as,
            "importCsv": self.import_csv_dialog,
            "importExcel": self.import_excel_dialog,
            "importData": self.import_data_dialog,
            "enterData": self.enter_data_dialog,
            "pasteData": lambda: self.enter_data_dialog(use_clipboard=True),
            "sampleData": self.load_sample_data,
            "transformData": self.transform_data_dialog,
            "appendQueries": self.append_queries_dialog,
            "mergeQueries": self.merge_queries_dialog,
            "newCalculatedTable": self.calculated_table_dialog,
            "newCalendarTable": self.calendar_table_dialog,
            "markDateTable": self.mark_date_table_dialog,
            "newMeasure": self.new_measure_dialog,
            "newCalculatedColumn": self.calculated_column_dialog,
            "quickMeasure": self.quick_measure_dialog,
            "manageRelationships": self.manage_relationships,
            "exportData": self.export_data_dialog,
            "refreshSource": self.refresh_source,
            "refreshAllSources": self.refresh_all_sources,
            "clearFilters": self.clear_filters,
            "addPage": self.add_page,
            "addMonthlyChart": lambda: self.add_chart("Monthly revenue"),
            "addRegionChart": lambda: self.add_chart("Region revenue"),
            "about": self.show_about,
            "shortcuts": self.show_shortcuts,
            "projectFormat": self.show_project_format,
            "quit": self.quit_application,
        }
        action = commands.get(command_id)
        if action is None:
            self._set_status(f"Unsupported command: {command_id}")
            return
        action()

    @Slot(result=bool)
    def manage_relationships(self) -> bool:
        """Create, edit, or remove validated relationships between loaded tables."""
        eligible_tables = [
            table for table in self._table_catalog
            if table.get("loaded") and table.get("loadEnabled") and table.get("headers")
        ]
        existing_relationships = self._project.get("model", {}).get("relationships", [])
        if len(eligible_tables) < 2 and not existing_relationships:
            self._set_status("Load at least two tables before managing relationships.")
            return False
        dialog = RelationshipDialog(
            self._table_catalog,
            existing_relationships,
            lambda candidate: self._validate_relationship_candidate(
                candidate, allow_unavailable=existing_relationships
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        relationships = dialog.relationships
        if relationships == self._project.get("model", {}).get("relationships", []):
            self._set_status("No relationship changes to save.")
            return True
        next_project = deepcopy(self._project)
        next_project.setdefault("model", {})["relationships"] = relationships
        try:
            next_project = validate_project(next_project)
        except ProjectFileError as exc:
            QMessageBox.warning(None, "Could not save relationships", str(exc))
            return False
        self._project = next_project
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self._set_status(f"Saved {len(relationships):,} model relationship(s)")
        self.stateChanged.emit()
        return True

    def _validate_relationship_candidate(
        self,
        relationships: list[dict[str, Any]],
        *,
        allow_unavailable: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        model_tables = self._project.get("model", {}).get("tables", [])
        normalized = normalize_relationships(relationships, model_tables)
        unchanged_by_id = {
            str(relationship.get("id")): relationship
            for relationship in (allow_unavailable or [])
            if isinstance(relationship, dict) and relationship.get("id") is not None
        }
        table_catalog = {
            str(table.get("id")): table
            for table in self._table_catalog
            if table.get("id") is not None
        }
        for relationship in normalized:
            if relationship.get("relationship_version") != RELATIONSHIP_VERSION:
                continue
            from_id = str(relationship["from_table_id"])
            to_id = str(relationship["to_table_id"])
            from_table = table_catalog.get(from_id)
            to_table = table_catalog.get(to_id)
            if (
                relationship == unchanged_by_id.get(str(relationship.get("id")))
                and (
                    from_table is None
                    or to_table is None
                    or not from_table.get("loaded")
                    or not to_table.get("loaded")
                )
            ):
                # Preserve existing definitions when a linked source is missing or
                # excluded from model load; users can still edit or delete them.
                continue
            if from_table is None or to_table is None:
                raise RelationshipError("Both relationship tables must still exist in the model.")
            if not all(
                table.get("loaded") and table.get("loadEnabled")
                for table in (from_table, to_table)
            ):
                raise RelationshipError("Both relationship tables must be loaded and enabled for model use.")
            from_column = str(relationship["from_column"])
            to_column = str(relationship["to_column"])
            from_source_id = str(from_table.get("sourceId", ""))
            to_source_id = str(to_table.get("sourceId", ""))
            from_candidate = self._loaded_candidates.get(from_source_id)
            to_candidate = self._loaded_candidates.get(to_source_id)
            if from_candidate is None or to_candidate is None:
                raise RelationshipError("Both relationship sources must be available and loaded.")
            if from_column not in from_candidate.headers or to_column not in to_candidate.headers:
                raise RelationshipError("A relationship column is missing from its loaded table.")
            from_type = str(from_table.get("columnTypes", {}).get(from_column, "text"))
            to_type = str(to_table.get("columnTypes", {}).get(to_column, "text"))
            compatible_types = from_type == to_type or {from_type, to_type} <= {
                "whole_number", "decimal_number",
            }
            if not compatible_types:
                raise RelationshipError(
                    f"Relationship column types must match; {from_type.replace('_', ' ')} "
                    f"cannot be related to {to_type.replace('_', ' ')}."
                )

            if relationship["cardinality"] in {"one_to_one", "one_to_many"}:
                _require_unique_relationship_values(
                    from_candidate.rows,
                    from_column,
                    str(from_table.get("name", "From table")),
                    from_type,
                )
            if relationship["cardinality"] in {"one_to_one", "many_to_one"}:
                _require_unique_relationship_values(
                    to_candidate.rows,
                    to_column,
                    str(to_table.get("name", "To table")),
                    to_type,
                )
            relationship["from"] = (
                f"{from_table.get('name', from_id)}[{from_column}]"
            )
            relationship["to"] = f"{to_table.get('name', to_id)}[{to_column}]"
        return normalized

    def _model_relationship_label(self, relationship: dict[str, Any]) -> str:
        if relationship.get("relationship_version") != RELATIONSHIP_VERSION:
            return f"{relationship.get('from', '?')} → {relationship.get('to', '?')} · legacy"
        tables_by_id = {
            str(table.get("id")): table for table in self._table_catalog
        }
        from_table = tables_by_id.get(str(relationship.get("from_table_id", "")), {})
        to_table = tables_by_id.get(str(relationship.get("to_table_id", "")), {})
        from_label = f"{from_table.get('name', relationship.get('from_table_id'))}[{relationship.get('from_column', '?')}]"
        to_label = f"{to_table.get('name', relationship.get('to_table_id'))}[{relationship.get('to_column', '?')}]"
        cardinality = str(relationship.get("cardinality", "")).replace("_", "-")
        state = "active" if relationship.get("is_active") else "inactive"
        direction = str(relationship.get("cross_filter_direction", "single"))
        return f"{from_label} → {to_label} · {cardinality} · {direction} · {state}"

    @Slot(int)
    def openRecentSource(self, index: int) -> bool:  # noqa: N802
        sources = self._recent_source_store.sources
        if index < 0 or index >= len(sources):
            self._set_status("That recent source is no longer in the list.")
            return False
        source = sources[index]
        path = Path(source.path)
        if not source.exists:
            self._set_status(f"Recent source is missing: {source.display_name}")
            self.stateChanged.emit()
            return False
        if source.kind == "folder":
            return self._import_folder_path(
                path,
                initial_options=source.parser_options,
            )
        return self._import_file_path(
            path,
            expected_kind=source.kind,
            initial_options=source.parser_options,
        )

    @Slot(str, result=bool)
    def selectTable(self, source_id: str) -> bool:  # noqa: N802
        """Make one model-loaded local table active for the data and report views."""
        parsed = self._loaded_candidates.get(source_id)
        if parsed is None:
            self._set_status("That table is not currently available.")
            return False
        if source_id == self._active_source_id:
            return True
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == source_id),
            None,
        )
        if source is None:
            self._set_status("The selected table has no data source record.")
            return False
        if not self._source_load_enabled(source):
            self._set_status("Enable load for this query before selecting it as a model table.")
            return False

        next_project = deepcopy(self._project)
        next_project["active_source_id"] = source_id
        try:
            self._project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not select table: {exc}")
            return False
        self._source_load_errors.pop("__active_selection__", None)
        path = (
            self._resolved_source_path(source)
            if source.get("kind") not in PATHLESS_SOURCE_KINDS
            else None
        )
        self._install_source(path, source_id, parsed)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Selected {self._active_model_table_name()}")
        return True

    @Slot(str, result=bool)
    def editQueryGroup(self, source_id: str) -> bool:  # noqa: N802
        """Assign an item to a named query group, or clear its group."""
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == source_id),
            None,
        )
        if source is None:
            self._set_status("That query is no longer in this project.")
            return False
        group_name, accepted = QInputDialog.getText(
            None,
            "Set query group",
            "Group name (leave empty to remove from its group):",
            text=str(source.get("query_group", "")),
        )
        if not accepted:
            return False
        group_name = group_name.strip()
        if (
            len(group_name) > 80
            or "\x00" in group_name
            or any(ord(char) < 32 for char in group_name)
        ):
            self._set_status("A query group name must be at most 80 characters and contain no control characters.")
            return False

        next_project = deepcopy(self._project)
        next_source = next(
            item for item in next_project["data_sources"]
            if item.get("id") == source_id
        )
        if group_name:
            next_source["query_group"] = group_name
        else:
            next_source.pop("query_group", None)
        try:
            self._project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not update query group: {exc}")
            return False
        self._dirty = True
        self._refresh_model_view()
        self.stateChanged.emit()
        self._set_status(
            f"Moved {source.get('name', 'query')} to {group_name}"
            if group_name else f"Removed {source.get('name', 'query')} from its group"
        )
        return True

    @Slot(str, bool, result=bool)
    def setQueryLoadEnabled(self, source_id: str, enabled: bool) -> bool:  # noqa: N802
        """Include or exclude one saved query result from the local model."""
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == source_id),
            None,
        )
        if source is None or source.get("kind") != "query":
            self._set_status("Choose a saved query to change its load setting.")
            return False
        enabled = bool(enabled)
        if self._source_load_enabled(source) == enabled:
            return True
        if enabled and source_id not in self._loaded_candidates:
            self._set_status("This query is unavailable and cannot be loaded into the model.")
            return False

        next_project = deepcopy(self._project)
        next_source = next(
            item for item in next_project["data_sources"]
            if item.get("id") == source_id
        )
        next_source["load_enabled"] = enabled
        active_source_id = self._active_source_id
        if not enabled and active_source_id == source_id:
            active_source_id = next(
                (
                    str(item["id"])
                    for item in next_project["data_sources"]
                    if item.get("id") != source_id
                    and self._source_load_enabled(item)
                    and item.get("id") in self._loaded_candidates
                ),
                None,
            )
        elif enabled and active_source_id is None:
            active_source_id = source_id
        next_project["active_source_id"] = active_source_id
        try:
            self._project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not update query load setting: {exc}")
            return False

        self._source_load_errors.pop("__active_selection__", None)
        if active_source_id != self._active_source_id:
            if active_source_id is None:
                self._clear_source(clear_selection=True)
            else:
                active_source = next(
                    item for item in self._project["data_sources"]
                    if item.get("id") == active_source_id
                )
                active_path = (
                    self._resolved_source_path(active_source)
                    if active_source.get("kind") not in PATHLESS_SOURCE_KINDS
                    else None
                )
                self._install_source(
                    active_path,
                    active_source_id,
                    self._loaded_candidates[active_source_id],
                )
        self._source_warning = self._compose_source_warning()
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(
            f"Enabled model load for {source.get('name', 'query')}"
            if enabled else f"Disabled model load for {source.get('name', 'query')}"
        )
        return True

    @Slot(str, bool, result=bool)
    def setQueryRefreshIncluded(self, source_id: str, included: bool) -> bool:  # noqa: N802
        """Set whether an individual saved query participates in refresh."""
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == source_id),
            None,
        )
        if source is None or source.get("kind") != "query":
            self._set_status("Choose a saved query to change its refresh setting.")
            return False
        included = bool(included)
        if self._source_refresh_included(source) == included:
            return True

        next_project = deepcopy(self._project)
        next_source = next(
            item for item in next_project["data_sources"]
            if item.get("id") == source_id
        )
        next_source["include_in_report_refresh"] = included
        try:
            self._project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not update query refresh setting: {exc}")
            return False

        self._dirty = True
        self._refresh_model_view()
        self.stateChanged.emit()
        self._set_status(
            f"Included {source.get('name', 'query')} in report refresh"
            if included else f"Excluded {source.get('name', 'query')} from report refresh"
        )
        return True

    @Slot(str, result=bool)
    def removeTable(self, source_id: str) -> bool:  # noqa: N802
        """Remove a table from the project without deleting its external file."""
        source = next(
            (item for item in self._project.get("data_sources", [])
             if item.get("id") == source_id),
            None,
        )
        if source is None:
            self._set_status("That table is no longer in this project.")
            return False
        dependent_queries = [
            str(item.get("name", "query"))
            for item in self._project.get("data_sources", [])
            if item.get("kind") == "query"
            and source_id in item.get("query_definition", {}).get("source_ids", [])
        ]
        if dependent_queries:
            names = ", ".join(dependent_queries)
            self._set_status(f"Remove dependent queries first: {names}")
            QMessageBox.warning(
                None,
                "Table has dependent queries",
                f"Remove these dependent queries before removing this table: {names}",
            )
            return False
        table = next(
            (item for item in self._project.get("model", {}).get("tables", [])
             if item.get("id") == source_id or item.get("source_id") == source_id),
            None,
        )
        table_name = str(table.get("name")) if table else str(source.get("name", "table"))
        answer = QMessageBox.question(
            None,
            "Remove table",
            f"Remove {table_name} and its saved transformations from this project? Linked files on disk will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False

        next_project = deepcopy(self._project)
        next_project["data_sources"] = [
            item for item in next_project.get("data_sources", [])
            if item.get("id") != source_id
        ]
        next_project["model"]["tables"] = [
            item for item in next_project["model"].get("tables", [])
            if item.get("id") != source_id and item.get("source_id") != source_id
        ]
        removed_table_ids = {source_id}
        if table is not None:
            removed_table_ids.add(str(table.get("id", "")))
        reference_prefixes = (f"{table_name}.", f"{table_name}[")
        next_project["model"]["relationships"] = [
            relationship
            for relationship in next_project["model"].get("relationships", [])
            if not (
                str(relationship.get("from_table_id", "")) in removed_table_ids
                or str(relationship.get("to_table_id", "")) in removed_table_ids
                or any(
                    str(relationship.get(endpoint, "")) in {source_id, table_name}
                    or str(relationship.get(endpoint, "")).startswith(reference_prefixes)
                    for endpoint in ("from", "to")
                )
            )
        ]

        removing_active = self._active_source_id == source_id
        remaining_source_ids = [
            str(item["id"]) for item in next_project["data_sources"]
        ]
        next_active_id = self._active_source_id
        if removing_active:
            next_active_id = next(
                (
                    str(item["id"])
                    for item in next_project["data_sources"]
                    if item.get("id") in remaining_source_ids
                    and item.get("id") in self._loaded_candidates
                    and self._source_load_enabled(item)
                ),
                None,
            )
        next_project["active_source_id"] = next_active_id
        try:
            self._project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not remove table: {exc}")
            return False

        credential_cleanup_failed = False
        if source.get("kind") == "sql_server":
            credential_ref = str(source.get("connection", {}).get("credential_ref", ""))
            still_used = any(
                item.get("kind") == "sql_server"
                and item.get("connection", {}).get("credential_ref") == credential_ref
                for item in self._project.get("data_sources", [])
            )
            if credential_ref and not still_used:
                self._sql_server_passwords.pop(credential_ref, None)
                try:
                    delete_sql_server_password(credential_ref)
                except CredentialStoreError:
                    credential_cleanup_failed = True

        self._loaded_candidates.pop(source_id, None)
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        if removing_active:
            if next_active_id in self._loaded_candidates:
                next_source = next(
                    item for item in self._project["data_sources"]
                    if item.get("id") == next_active_id
                )
                next_path = (
                    self._resolved_source_path(next_source)
                    if next_source.get("kind") not in PATHLESS_SOURCE_KINDS
                    else None
                )
                self._install_source(next_path, next_active_id, self._loaded_candidates[next_active_id])
            else:
                self._clear_source(clear_selection=True)
                self._active_source_id = next_active_id
                next_source = next(
                    (item for item in self._project["data_sources"]
                     if item.get("id") == next_active_id),
                    None,
                )
                self._active_source_path = (
                    self._resolved_source_path(next_source)
                    if next_source and next_source.get("kind") not in PATHLESS_SOURCE_KINDS
                    else None
                )
                self._active_source_kind = str(next_source.get("kind")) if next_source else None
                self._active_parser_options = dict(next_source.get("parser_options", {})) if next_source else {}

        self._source_warning = self._compose_source_warning()
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        suffix = "; its unused SQL Server credential remains in Keychain" if credential_cleanup_failed else ""
        self._set_status(f"Removed {table_name} from this project{suffix}")
        return True

    @Slot(str, result=bool)
    def connectDataSource(self, source_id: str) -> bool:  # noqa: N802
        """Dispatch connector choices that have an implemented local workflow."""
        source = next((item for item in DATA_SOURCE_CATALOG if item["id"] == source_id), None)
        if source is None:
            self._set_status("Unknown data source selection")
            return False
        if not source["implemented"]:
            self._set_status(f"{source['name']} is cataloged; its connector is not implemented.")
            return False
        source_kind = {
            "file_text_csv": "csv",
            "file_excel_workbook": "excel",
            "file_json": "json",
            "file_xml": "xml",
            "file_parquet": "parquet",
            "database_sqlite_database": "sqlite",
            "microsoft_sql_server": "sql_server",
            "other_odata_feed": "odata",
            "other_web": "web",
        }.get(source_id)
        if source_kind == "sql_server":
            return self._import_sql_server_dialog()
        if source_kind == "odata":
            return self._import_odata_dialog()
        if source_kind == "web":
            return self._import_web_dialog()
        if source_id == "file_folder":
            self.import_folder_dialog()
            return True
        if source_kind:
            self.import_data_dialog(expected_kind=source_kind)
            return True
        self._set_status(f"{source['name']} does not have an importer in this release.")
        return False

    def _import_odata_dialog(self) -> bool:
        dialog = ODataFeedImportDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_odata_import(
            {"service_root": dialog.service_root},
            dialog.candidate,
        )

    def _import_web_dialog(self) -> bool:
        dialog = WebImportDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_web_import({"url": dialog.url}, dialog.candidate)

    def _commit_web_import(
        self,
        connection: dict[str, Any],
        parsed: ImportCandidate,
    ) -> bool:
        options = dict(parsed.options)
        url = connection["url"]
        existing_source = next((
            source for source in self._project.get("data_sources", [])
            if source.get("kind") == "web"
            and source.get("connection", {}).get("url") == url
            and source.get("parser_options") == options
        ), None)
        source_id = str(existing_source["id"]) if existing_source else str(uuid4())
        existing_table = next(
            (table for table in self._project.get("model", {}).get("tables", [])
             if table.get("id") == source_id or table.get("source_id") == source_id),
            None,
        )
        desired_table_name = _web_table_name(url, options)
        table_name = (
            str(existing_table.get("name"))
            if existing_table is not None
            else self._unique_table_name(desired_table_name)
        )
        source_name = f"{table_name} · Web"
        transform_steps = list(existing_source.get("transform_steps", [])) if existing_source else []
        source_record = {
            "id": source_id,
            "name": source_name,
            "kind": "web",
            "connection": dict(connection),
            "parser_options": options,
            "transform_steps": transform_steps,
        }
        sources = list(self._project.get("data_sources", []))
        updated_sources = []
        replaced = False
        for source in sources:
            if source.get("id") == source_id:
                updated_sources.append({**source, **source_record})
                replaced = True
            else:
                updated_sources.append(source)
        if not replaced:
            updated_sources.append(source_record)

        next_project = deepcopy(self._project)
        next_project["data_sources"] = updated_sources
        next_project["active_source_id"] = source_id
        model = next_project.setdefault("model", {"tables": [], "relationships": []})
        table_record = {
            "id": source_id,
            "name": table_name,
            "source_id": source_id,
            "column_types": {header: "text" for header in parsed.headers},
        }
        tables = list(model.get("tables", []))
        for index, table in enumerate(tables):
            if table.get("id") == source_id or table.get("source_id") == source_id:
                tables[index] = {**table, **table_record}
                break
        else:
            tables.append(table_record)
        model["tables"] = tables
        try:
            source_candidate = apply_transformations(parsed, transform_steps)
            base_types = column_types_after_steps(
                parsed.headers, transform_steps, output_headers=source_candidate.headers
            )
            source_table = self._model_table_for_source(next_project, source_id)
            if source_table is not None:
                source_table["column_types"] = base_types
            source_candidate, calculated_types = self._apply_calculated_columns(
                source_id, source_candidate, project=next_project,
                column_types=base_types,
            )
            if source_table is not None:
                source_table["column_types"] = {
                    **base_types, **calculated_types
                }
            next_project = validate_project(next_project)
            dependent_candidates, dependent_types = self._rebuild_query_dependents(
                next_project, {source_id: source_candidate}
            )
            for dependent_id, type_map in dependent_types.items():
                table = next(
                    (item for item in next_project["model"]["tables"]
                     if item.get("id") == dependent_id or item.get("source_id") == dependent_id),
                    None,
                )
                if table is not None:
                    table["column_types"] = type_map
            next_project = validate_project(next_project)
        except (ProjectFileError, QueryError, OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(None, "Could not import Web data", str(exc))
            return False

        self._project = next_project
        self._active_source_id = source_id
        self._active_source_path = None
        self._active_source_kind = "web"
        self._active_parser_options = options
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._loaded_candidates.update(dependent_candidates)
        for updated_id in dependent_candidates:
            self._source_load_errors.pop(updated_id, None)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._install_source(None, source_id, source_candidate)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        notice = f" · {parsed.notices[0]}" if parsed.notices else ""
        self._set_status(f"Loaded {source_name} · {parsed.row_count:,} rows{notice}")
        return True

    def _commit_odata_import(
        self,
        connection: dict[str, Any],
        parsed: ImportCandidate,
    ) -> bool:
        options = dict(parsed.options)
        service_root = connection["service_root"]
        existing_source = next((
            source for source in self._project.get("data_sources", [])
            if source.get("kind") == "odata"
            and source.get("connection", {}).get("service_root") == service_root
            and source.get("parser_options") == options
        ), None)
        source_id = str(existing_source["id"]) if existing_source else str(uuid4())
        existing_table = next(
            (table for table in self._project.get("model", {}).get("tables", [])
             if table.get("id") == source_id or table.get("source_id") == source_id),
            None,
        )
        entity_set_name = options["entity_set_name"]
        table_name = (
            str(existing_table.get("name"))
            if existing_table is not None
            else self._unique_table_name(entity_set_name)
        )
        source_name = f"{entity_set_name} · OData Feed"
        transform_steps = list(existing_source.get("transform_steps", [])) if existing_source else []
        source_record = {
            "id": source_id,
            "name": source_name,
            "kind": "odata",
            "connection": dict(connection),
            "parser_options": options,
            "transform_steps": transform_steps,
        }
        sources = list(self._project.get("data_sources", []))
        updated_sources = []
        replaced = False
        for source in sources:
            if source.get("id") == source_id:
                updated_sources.append({**source, **source_record})
                replaced = True
            else:
                updated_sources.append(source)
        if not replaced:
            updated_sources.append(source_record)

        next_project = deepcopy(self._project)
        next_project["data_sources"] = updated_sources
        next_project["active_source_id"] = source_id
        model = next_project.setdefault("model", {"tables": [], "relationships": []})
        table_record = {
            "id": source_id,
            "name": table_name,
            "source_id": source_id,
            "column_types": {header: "text" for header in parsed.headers},
        }
        tables = list(model.get("tables", []))
        for index, table in enumerate(tables):
            if table.get("id") == source_id or table.get("source_id") == source_id:
                tables[index] = {**table, **table_record}
                break
        else:
            tables.append(table_record)
        model["tables"] = tables
        try:
            source_candidate = apply_transformations(parsed, transform_steps)
            base_types = column_types_after_steps(
                parsed.headers, transform_steps, output_headers=source_candidate.headers
            )
            source_table = self._model_table_for_source(next_project, source_id)
            if source_table is not None:
                source_table["column_types"] = base_types
            source_candidate, calculated_types = self._apply_calculated_columns(
                source_id, source_candidate, project=next_project,
                column_types=base_types,
            )
            if source_table is not None:
                source_table["column_types"] = {
                    **base_types, **calculated_types
                }
            next_project = validate_project(next_project)
            dependent_candidates, dependent_types = self._rebuild_query_dependents(
                next_project, {source_id: source_candidate}
            )
            for dependent_id, type_map in dependent_types.items():
                table = next(
                    (item for item in next_project["model"]["tables"]
                     if item.get("id") == dependent_id or item.get("source_id") == dependent_id),
                    None,
                )
                if table is not None:
                    table["column_types"] = type_map
            next_project = validate_project(next_project)
        except (ProjectFileError, QueryError, OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(None, "Could not import OData Feed data", str(exc))
            return False

        self._project = next_project
        self._active_source_id = source_id
        self._active_source_path = None
        self._active_source_kind = "odata"
        self._active_parser_options = options
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._loaded_candidates.update(dependent_candidates)
        for updated_id in dependent_candidates:
            self._source_load_errors.pop(updated_id, None)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._install_source(None, source_id, source_candidate)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        notice = f" · {parsed.notices[0]}" if parsed.notices else ""
        self._set_status(f"Loaded {source_name} · {parsed.row_count:,} rows{notice}")
        return True

    def _import_sql_server_dialog(self) -> bool:
        dialog = SQLServerImportDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_sql_server_import(
            dialog.connection_settings,
            dialog.password,
            dialog.candidate,
        )

    def _commit_sql_server_import(
        self,
        settings: dict[str, Any],
        password: str,
        parsed: ImportCandidate,
    ) -> bool:
        options = dict(parsed.options)
        identity = (settings["server"], settings["port"], settings["database"], settings["username"])
        existing_source = next((
            source for source in self._project.get("data_sources", [])
            if self._sql_server_source_matches(source, identity, options)
        ), None)
        source_id = str(existing_source["id"]) if existing_source else str(uuid4())
        connection_source = existing_source or next((
            source for source in self._project.get("data_sources", [])
            if self._sql_server_connection_matches(source, identity)
        ), None)
        credential_ref = (
            str(connection_source.get("connection", {}).get("credential_ref"))
            if connection_source else str(uuid4())
        )
        connection = {
            **settings,
            "credential_ref": credential_ref,
        }
        existing_table = next(
            (table for table in self._project.get("model", {}).get("tables", [])
             if table.get("id") == source_id or table.get("source_id") == source_id),
            None,
        )
        table_name = (
            str(existing_table.get("name"))
            if existing_table is not None
            else self._unique_table_name(options["table_name"])
        )
        source_name = f"{settings['database']}.{options['schema']}.{options['table_name']}"
        transform_steps = list(existing_source.get("transform_steps", [])) if existing_source else []
        source_record = {
            "id": source_id,
            "name": source_name,
            "kind": "sql_server",
            "connection": connection,
            "parser_options": options,
            "transform_steps": transform_steps,
        }
        sources = list(self._project.get("data_sources", []))
        updated_sources = []
        replaced = False
        for source in sources:
            if source.get("id") == source_id:
                updated_sources.append({**source, **source_record})
                replaced = True
            else:
                updated_sources.append(source)
        if not replaced:
            updated_sources.append(source_record)

        next_project = deepcopy(self._project)
        next_project["data_sources"] = updated_sources
        next_project["active_source_id"] = source_id
        model = next_project.setdefault("model", {"tables": [], "relationships": []})
        table_record = {
            "id": source_id,
            "name": table_name,
            "source_id": source_id,
            "column_types": {header: "text" for header in parsed.headers},
        }
        tables = list(model.get("tables", []))
        table_replaced = False
        for index, table in enumerate(tables):
            if table.get("id") == source_id or table.get("source_id") == source_id:
                tables[index] = {**table, **table_record}
                table_replaced = True
                break
        if not table_replaced:
            tables.append(table_record)
        model["tables"] = tables
        try:
            source_candidate = apply_transformations(parsed, transform_steps)
            base_types = column_types_after_steps(
                parsed.headers, transform_steps, output_headers=source_candidate.headers
            )
            source_table = self._model_table_for_source(next_project, source_id)
            if source_table is not None:
                source_table["column_types"] = base_types
            source_candidate, calculated_types = self._apply_calculated_columns(
                source_id, source_candidate, project=next_project,
                column_types=base_types,
            )
            if source_table is not None:
                source_table["column_types"] = {
                    **base_types, **calculated_types
                }
            next_project = validate_project(next_project)
            dependent_candidates, dependent_types = self._rebuild_query_dependents(
                next_project, {source_id: source_candidate}
            )
            for dependent_id, type_map in dependent_types.items():
                table = next(
                    (item for item in next_project["model"]["tables"]
                     if item.get("id") == dependent_id or item.get("source_id") == dependent_id),
                    None,
                )
                if table is not None:
                    table["column_types"] = type_map
            next_project = validate_project(next_project)
        except (ProjectFileError, QueryError, OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(None, "Could not import SQL Server data", str(exc))
            return False

        try:
            set_sql_server_password(credential_ref, password)
        except CredentialStoreError as exc:
            QMessageBox.critical(None, "Could not save SQL Server credentials", str(exc))
            return False

        self._sql_server_passwords[credential_ref] = password
        self._project = next_project
        self._active_source_id = source_id
        self._active_source_path = None
        self._active_source_kind = "sql_server"
        self._active_parser_options = options
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._loaded_candidates.update(dependent_candidates)
        for updated_id in dependent_candidates:
            self._source_load_errors.pop(updated_id, None)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._install_source(None, source_id, source_candidate)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Loaded {source_name} · {parsed.row_count:,} rows")
        return True

    @staticmethod
    def _sql_server_source_matches(
        source: dict[str, Any],
        identity: tuple[str, int, str, str],
        options: dict[str, Any],
    ) -> bool:
        connection = source.get("connection", {})
        return (
            source.get("kind") == "sql_server"
            and connection.get("server") == identity[0]
            and connection.get("port") == identity[1]
            and connection.get("database") == identity[2]
            and connection.get("username") == identity[3]
            and source.get("parser_options") == options
        )

    @staticmethod
    def _sql_server_connection_matches(
        source: dict[str, Any], identity: tuple[str, int, str, str]
    ) -> bool:
        connection = source.get("connection", {})
        return (
            source.get("kind") == "sql_server"
            and connection.get("server") == identity[0]
            and connection.get("port") == identity[1]
            and connection.get("database") == identity[2]
            and connection.get("username") == identity[3]
        )

    @Slot(str, str)
    def reportStagedAction(self, name: str, reason: str) -> None:  # noqa: N802
        """Show honest UI-only feedback for a visible but inactive command."""
        label = (name or "This action").strip()
        detail = (reason or "This workflow is not available in this release.").strip()
        self._set_status(f"{label} · {detail}")

    @Slot(str)
    def setCurrentView(self, view_name: str) -> None:  # noqa: N802
        if view_name not in {"Report", "Data", "Model"}:
            return
        if self._current_view == view_name:
            return
        self._current_view = view_name
        self._dirty = True
        self._set_status(f"{view_name} view")
        self.stateChanged.emit()

    @Slot(int)
    def setActivePage(self, index: int) -> None:  # noqa: N802
        pages = self._project["report"]["pages"]
        if index < 0 or index >= len(pages):
            return
        page_id = pages[index]["id"]
        if self._active_page_id == page_id:
            return
        self._active_page_id = page_id
        self._project["report"]["active_page_id"] = page_id
        self._selected_visual = ""
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str)
    def selectVisual(self, visual_name: str) -> None:  # noqa: N802
        if visual_name not in self.activePageVisuals:
            return
        if self._selected_visual == visual_name:
            return
        self._selected_visual = visual_name
        self.stateChanged.emit()

    @Slot(str)
    def setChartType(self, chart_type: str) -> None:  # noqa: N802
        key = self._chart_key(self._selected_visual)
        if key is None or chart_type not in CHART_TYPES:
            return
        if self._project["report"]["chart_types"][key] == chart_type:
            return
        self._project["report"]["chart_types"][key] = chart_type
        self._dirty = True
        self.stateChanged.emit()

    @Slot(str)
    def setRegionFilter(self, region: str) -> None:  # noqa: N802
        next_region = None if region in ("", "All regions") else region
        if next_region is not None and next_region not in self.regions:
            return
        if self._current_region == next_region:
            return
        self._current_region = next_region
        self._refresh_report()
        self.stateChanged.emit()

    def _add_report_filter(
        self,
        *,
        table_id: str,
        column: str,
        operator: str,
        value: str,
        second_operator: str = "",
        second_value: str = "",
        logic: str = "and",
        visual_name: str = "",
        multi_values: list[str] | None = None,
        relative_date_rule: dict[str, Any] | None = None,
        relative_time_rule: dict[str, Any] | None = None,
        top_n_rule: dict[str, Any] | None = None,
        report_scope: bool = False,
    ) -> bool:
        table = next(
            (item for item in self._table_catalog
             if item.get("id") == table_id and item.get("loaded") and item.get("loadEnabled")),
            None,
        )
        candidate = self._loaded_candidates.get(str(table.get("sourceId", ""))) if table else None
        if candidate is None or column not in candidate.headers:
            self._set_status("Choose a loaded table field for the filter.")
            return False
        page = self._active_page()
        if page is None:
            self._set_status("Choose a report page before adding a filter.")
            return False
        if visual_name and visual_name not in self.activePageVisuals:
            self._set_status("Select a visual on this page before adding a visual filter.")
            return False
        if report_scope and visual_name:
            self._set_status("A report-wide filter cannot target one visual.")
            return False

        column_type = str(table.get("columnTypes", {}).get(column, "text"))
        allowed_operators = _report_filter_operators(column_type)
        clauses: list[dict[str, Any]] = []
        if operator == _REPORT_FILTER_TOP_N:
            active_table_id = self._active_model_table_id()
            region_column = _report_field(candidate.headers, "region")
            if (
                not visual_name
                or visual_name != "Region revenue"
                or table_id != active_table_id
                or column != region_column
            ):
                self._set_status("Top N is available on the Region revenue chart's category field.")
                return False
            if second_operator or second_value or multi_values is not None:
                self._set_status("Top N filters use one rule per visual category field.")
                return False
            if not isinstance(top_n_rule, dict) or set(top_n_rule) != {
                "direction", "count", "order_by_column"
            }:
                self._set_status("Choose Top or Bottom, an item count, and an order-by field.")
                return False
            direction = top_n_rule.get("direction")
            count = top_n_rule.get("count")
            order_by_column = top_n_rule.get("order_by_column")
            if direction not in {"top", "bottom"}:
                self._set_status("Choose Top or Bottom for the Top N filter.")
                return False
            if type(count) is not int or not 1 <= count <= 1000:
                self._set_status("Choose between 1 and 1000 items for the Top N filter.")
                return False
            if not isinstance(order_by_column, str) or order_by_column not in candidate.headers:
                self._set_status("Choose a numeric field from the active table to order by.")
                return False
            if order_by_column == column:
                self._set_status("Choose a numeric field other than the category field.")
                return False
            if not any(_report_number(row.get(order_by_column)) is not None for row in candidate.rows):
                self._set_status("The order-by field has no numeric values in the active table.")
                return False
            clauses.append({
                "operator": _REPORT_FILTER_TOP_N,
                "direction": direction,
                "count": count,
                "order_by": {"table_id": table_id, "column": order_by_column},
            })
            logic = "and"
        elif operator == _REPORT_FILTER_RELATIVE_DATE:
            if operator not in allowed_operators or column_type != "date":
                self._set_status("Relative-date filters need a date-typed field.")
                return False
            if second_operator or second_value or multi_values is not None:
                self._set_status("Relative-date filters use one condition per field.")
                return False
            if not isinstance(relative_date_rule, dict) or set(relative_date_rule) != {
                "direction", "count", "unit", "include_today"
            }:
                self._set_status("Choose a complete relative-date rule.")
                return False
            direction = relative_date_rule.get("direction")
            count = relative_date_rule.get("count")
            unit = relative_date_rule.get("unit")
            include_today = relative_date_rule.get("include_today")
            if direction not in {"last", "this", "next"}:
                self._set_status("Choose Last, This, or Next for the relative-date rule.")
                return False
            if type(count) is not int or not 1 <= count <= 1000:
                self._set_status("Choose between 1 and 1000 relative periods.")
                return False
            if unit not in _REPORT_FILTER_RELATIVE_DATE_UNITS:
                self._set_status("Choose a supported relative-date unit.")
                return False
            if not isinstance(include_today, bool):
                self._set_status("Choose whether the rolling date range includes today.")
                return False
            clauses.append({
                "operator": _REPORT_FILTER_RELATIVE_DATE,
                "direction": direction,
                "count": 1 if direction == "this" else count,
                "unit": unit,
                "include_today": include_today,
            })
            logic = "and"
        elif operator == _REPORT_FILTER_RELATIVE_TIME:
            if operator not in allowed_operators or column_type != "datetime":
                self._set_status("Relative-time filters need a Date/time-typed field.")
                return False
            if second_operator or second_value or multi_values is not None:
                self._set_status("Relative-time filters use one condition per field.")
                return False
            if not isinstance(relative_time_rule, dict) or set(relative_time_rule) != {
                "direction", "count", "unit"
            }:
                self._set_status("Choose a complete relative-time rule.")
                return False
            direction = relative_time_rule.get("direction")
            count = relative_time_rule.get("count")
            unit = relative_time_rule.get("unit")
            if direction not in {"last", "this", "next"}:
                self._set_status("Choose Last, This, or Next for the relative-time rule.")
                return False
            if type(count) is not int or not 1 <= count <= 1000:
                self._set_status("Choose between 1 and 1000 relative periods.")
                return False
            if unit not in _REPORT_FILTER_RELATIVE_TIME_UNITS:
                self._set_status("Choose Minutes or Hours for the relative-time rule.")
                return False
            clauses.append({
                "operator": _REPORT_FILTER_RELATIVE_TIME,
                "direction": direction,
                "count": 1 if direction == "this" else count,
                "unit": unit,
            })
            logic = "and"
        elif operator in _REPORT_FILTER_MULTI_VALUE:
            if operator not in allowed_operators:
                self._set_status("Choose a filter operator supported by this field's type.")
                return False
            if second_operator or second_value:
                self._set_status("Multi-value filters use one condition per field.")
                return False
            if not isinstance(multi_values, list):
                self._set_status("Choose one or more values for this filter.")
                return False
            if any(not isinstance(item, str) for item in multi_values):
                self._set_status("Filter values must be text values from the selected field.")
                return False
            selected_values = list(dict.fromkeys(multi_values))
            if not 1 <= len(selected_values) <= 1000:
                self._set_status("Choose between 1 and 1000 distinct values.")
                return False
            if column_type in _REPORT_FILTER_NUMERIC_TYPES | _REPORT_FILTER_TEMPORAL_TYPES:
                try:
                    for selected_value in selected_values:
                        if selected_value:
                            _parse_report_filter_value(selected_value, column_type)
                except (DecimalException, ValueError) as exc:
                    self._set_status(str(exc) or "A selected value does not match this field's type.")
                    return False
            clauses.append({"operator": operator, "values": selected_values})
            logic = "and"
        else:
            if multi_values is not None:
                self._set_status("Multi-value selections need an any-of or none-of operator.")
                return False
            requested_clauses = [(operator, value)]
            if second_operator:
                requested_clauses.append((second_operator, second_value))
            elif second_value:
                self._set_status("A second comparison value needs a second condition.")
                return False
            for clause_operator, clause_value in requested_clauses:
                if clause_operator in {
                    _REPORT_FILTER_RELATIVE_DATE, _REPORT_FILTER_RELATIVE_TIME
                }:
                    self._set_status("Relative filters must be the only condition for their field.")
                    return False
                if clause_operator in _REPORT_FILTER_MULTI_VALUE:
                    self._set_status("A multi-value filter must be the only condition for its field.")
                    return False
                if clause_operator not in allowed_operators:
                    self._set_status("Choose a filter operator supported by this field's type.")
                    return False
                if clause_operator in _REPORT_FILTER_VALUELESS:
                    if clause_value:
                        self._set_status("Blank checks do not take a comparison value.")
                        return False
                elif clause_operator in _REPORT_FILTER_REQUIRED_VALUE and not clause_value:
                    self._set_status("This filter condition needs a comparison value.")
                    return False
                elif column_type in _REPORT_FILTER_NUMERIC_TYPES | _REPORT_FILTER_TEMPORAL_TYPES:
                    try:
                        _parse_report_filter_value(clause_value, column_type)
                    except (DecimalException, ValueError) as exc:
                        self._set_status(str(exc) or "Enter a valid comparison value for this field.")
                        return False
                clauses.append({"operator": clause_operator, "value": clause_value})
        if len(clauses) == 2 and logic not in {"and", "or"}:
            self._set_status("Choose AND or OR for the two filter conditions.")
            return False
        if len(clauses) == 1:
            logic = "and"

        filters_key = "visual_filters" if visual_name else "filters"
        next_project = deepcopy(self._project)
        if report_scope:
            filter_owner = next_project["report"]
        else:
            filter_owner = next(
                item for item in next_project["report"]["pages"]
                if item["id"] == self._active_page_id
            )
        filters = filter_owner.setdefault(filters_key, [])
        if visual_name:
            filters[:] = [
                item for item in filters
                if (item["visual_name"], item["table_id"], item["column"])
                != (visual_name, table_id, column)
            ]
        else:
            filters[:] = [
                item for item in filters
                if (item["table_id"], item["column"]) != (table_id, column)
            ]
        if len(filters) >= 256:
            scope_label = "report" if report_scope else "report page"
            self._set_status(f"A {scope_label} can contain at most 256 {filters_key.replace('_', ' ')}.")
            return False
        report_filter: dict[str, Any] = {
            "table_id": table_id,
            "column": column,
            "clauses": clauses,
            "logic": logic,
        }
        if visual_name:
            report_filter["visual_name"] = visual_name
        filters.append(report_filter)
        try:
            self._project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not add filter: {exc}")
            return False
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        summary = _report_filter_summary(clauses, logic)
        scope = (
            f"{visual_name} · " if visual_name
            else "all report pages · " if report_scope
            else ""
        )
        self._set_status(
            f"Filtered {scope}{table.get('name', 'table')} · {column} {summary}"
        )
        return True

    @Slot(str, str, str, result=bool)
    def addPageFilter(self, table_id: str, column: str, value: str) -> bool:  # noqa: N802
        return self._add_report_filter(
            table_id=table_id, column=column, operator="equals", value=value
        )

    @Slot(str, str, str, str, str, str, str, result=bool)
    def addPageFilterRule(
        self,
        table_id: str,
        column: str,
        operator: str,
        value: str,
        second_operator: str,
        second_value: str,
        logic: str,
    ) -> bool:  # noqa: N802
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=operator,
            value=value,
            second_operator=second_operator,
            second_value=second_value,
            logic=logic,
        )

    @Slot(str, str, str, str, str, str, str, result=bool)
    def addReportFilterRule(
        self,
        table_id: str,
        column: str,
        operator: str,
        value: str,
        second_operator: str,
        second_value: str,
        logic: str,
    ) -> bool:  # noqa: N802
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=operator,
            value=value,
            second_operator=second_operator,
            second_value=second_value,
            logic=logic,
            report_scope=True,
        )

    @Slot(str, str, str, str, result=bool)
    def addPageMultiValueFilter(  # noqa: N802
        self, table_id: str, column: str, operator: str, values_json: str
    ) -> bool:
        try:
            values = json.loads(values_json)
        except (json.JSONDecodeError, TypeError):
            self._set_status("The selected filter values are invalid.")
            return False
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=operator,
            value="",
            multi_values=values,
        )

    @Slot(str, str, str, str, result=bool)
    def addReportMultiValueFilter(  # noqa: N802
        self, table_id: str, column: str, operator: str, values_json: str
    ) -> bool:
        try:
            values = json.loads(values_json)
        except (json.JSONDecodeError, TypeError):
            self._set_status("The selected filter values are invalid.")
            return False
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=operator,
            value="",
            multi_values=values,
            report_scope=True,
        )

    @Slot(str, str, str, int, str, bool, result=bool)
    def addPageRelativeDateFilter(  # noqa: N802
        self,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        unit: str,
        include_today: bool,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_RELATIVE_DATE,
            value="",
            relative_date_rule={
                "direction": direction,
                "count": count,
                "unit": unit,
                "include_today": include_today,
            },
        )

    @Slot(str, str, str, int, str, bool, result=bool)
    def addReportRelativeDateFilter(  # noqa: N802
        self,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        unit: str,
        include_today: bool,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_RELATIVE_DATE,
            value="",
            relative_date_rule={
                "direction": direction,
                "count": count,
                "unit": unit,
                "include_today": include_today,
            },
            report_scope=True,
        )

    @Slot(str, str, str, int, str, result=bool)
    def addPageRelativeTimeFilter(  # noqa: N802
        self,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        unit: str,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_RELATIVE_TIME,
            value="",
            relative_time_rule={"direction": direction, "count": count, "unit": unit},
        )

    @Slot(str, str, str, int, str, result=bool)
    def addReportRelativeTimeFilter(  # noqa: N802
        self,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        unit: str,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_RELATIVE_TIME,
            value="",
            relative_time_rule={"direction": direction, "count": count, "unit": unit},
            report_scope=True,
        )

    @Slot(int, result=bool)
    def removeReportFilter(self, index: int) -> bool:  # noqa: N802
        filters = self._project.get("report", {}).get("filters", [])
        if index < 0 or index >= len(filters):
            return False
        removed = filters.pop(index)
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Removed report filter for {removed['column']}")
        return True

    @Slot(int, result=bool)
    def removePageFilter(self, index: int) -> bool:  # noqa: N802
        page = self._active_page()
        if page is None:
            return False
        filters = page.get("filters", [])
        if index < 0 or index >= len(filters):
            return False
        removed = filters.pop(index)
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Removed page filter for {removed['column']}")
        return True

    @Slot(str, str, str, str, result=bool)
    def addVisualFilter(
        self, visual_name: str, table_id: str, column: str, value: str
    ) -> bool:  # noqa: N802
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator="equals",
            value=value,
            visual_name=visual_name,
        )

    @Slot(str, str, str, str, str, str, str, str, result=bool)
    def addVisualFilterRule(
        self,
        visual_name: str,
        table_id: str,
        column: str,
        operator: str,
        value: str,
        second_operator: str,
        second_value: str,
        logic: str,
    ) -> bool:  # noqa: N802
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=operator,
            value=value,
            second_operator=second_operator,
            second_value=second_value,
            logic=logic,
            visual_name=visual_name,
        )

    @Slot(str, str, str, str, str, result=bool)
    def addVisualMultiValueFilter(  # noqa: N802
        self,
        visual_name: str,
        table_id: str,
        column: str,
        operator: str,
        values_json: str,
    ) -> bool:
        try:
            values = json.loads(values_json)
        except (json.JSONDecodeError, TypeError):
            self._set_status("The selected filter values are invalid.")
            return False
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=operator,
            value="",
            visual_name=visual_name,
            multi_values=values,
        )

    @Slot(str, str, str, str, int, str, bool, result=bool)
    def addVisualRelativeDateFilter(  # noqa: N802
        self,
        visual_name: str,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        unit: str,
        include_today: bool,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_RELATIVE_DATE,
            value="",
            visual_name=visual_name,
            relative_date_rule={
                "direction": direction,
                "count": count,
                "unit": unit,
                "include_today": include_today,
            },
        )

    @Slot(str, str, str, str, int, str, result=bool)
    def addVisualRelativeTimeFilter(  # noqa: N802
        self,
        visual_name: str,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        unit: str,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_RELATIVE_TIME,
            value="",
            visual_name=visual_name,
            relative_time_rule={"direction": direction, "count": count, "unit": unit},
        )

    @Slot(str, str, str, str, int, str, result=bool)
    def addVisualTopNFilter(  # noqa: N802
        self,
        visual_name: str,
        table_id: str,
        column: str,
        direction: str,
        count: int,
        order_by_column: str,
    ) -> bool:
        return self._add_report_filter(
            table_id=table_id,
            column=column,
            operator=_REPORT_FILTER_TOP_N,
            value="",
            visual_name=visual_name,
            top_n_rule={
                "direction": direction,
                "count": count,
                "order_by_column": order_by_column,
            },
        )

    @Slot(int, result=bool)
    def removeVisualFilter(self, index: int) -> bool:  # noqa: N802
        page = self._active_page()
        if page is None or not self._selected_visual:
            return False
        filters = page.get("visual_filters", [])
        if index < 0 or index >= len(filters):
            return False
        if filters[index].get("visual_name") != self._selected_visual:
            return False
        removed = filters.pop(index)
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Removed filter from {self._selected_visual} · {removed['column']}")
        return True

    @Slot(str)
    def setFieldQuery(self, query: str) -> None:  # noqa: N802
        query = query or ""
        if self._field_query == query:
            return
        self._field_query = query
        self.stateChanged.emit()

    @Slot(result=bool)
    def confirmClose(self) -> bool:  # noqa: N802
        return self._confirm_replace_project()

    def new_project_dialog(self) -> None:
        if not self._confirm_replace_project():
            return
        self._replace_with_new_project()

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            None,
            "Open Analytics Studio project",
            "",
            "Analytics Studio projects (*.npa);;JSON files (*.json)",
        )
        if path:
            self.open_project_path(Path(path))

    def open_project_path(self, path: Path) -> bool:
        if not self._confirm_replace_project():
            return False
        path = Path(path).expanduser().resolve()
        try:
            candidate, recovered = load_project(path)
        except ProjectFileError as exc:
            QMessageBox.critical(None, "Could not open project", str(exc))
            return False
        except OSError as exc:
            QMessageBox.critical(None, "Could not open project", str(exc))
            return False

        # Resolve and parse the prospective source before swapping out the live document.
        candidate = deepcopy(candidate)
        for source in candidate.get("data_sources", []):
            if source.get("kind") not in PATHLESS_SOURCE_KINDS:
                source["path"] = str(resolve_source_path(source["path"], path))

        sources = candidate.get("data_sources", [])
        loaded_candidates: dict[str, ImportCandidate] = {}
        source_paths: dict[str, Path | None] = {}
        load_errors: dict[str, str] = {}
        warnings: list[str] = []
        metadata_changed = False
        for source in self._source_dependency_order(sources):
            source_id = str(source["id"])
            kind = str(source.get("kind", ""))
            source_path = (
                Path(source["path"])
                if kind not in PATHLESS_SOURCE_KINDS
                else None
            )
            source_paths[source_id] = source_path
            try:
                if kind == "inline":
                    raw = self._raw_candidate_for_source(source)
                elif kind == "query":
                    raw = self._query_candidate(source, loaded_candidates, project=candidate)
                elif kind == "sql_server":
                    raw = self._sql_server_candidate_for_source(source)
                elif kind == "odata":
                    raw = self._odata_candidate_for_source(source)
                elif kind == "web":
                    raw = self._web_candidate_for_source(source)
                elif kind == "folder" and source_path is not None:
                    raw = parse_folder(
                        source_path,
                        options=source.get("parser_options", {}),
                    )
                elif kind in SUPPORTED_SOURCE_KINDS and source_path is not None:
                    if not source_path.is_file():
                        raise FileNotFoundError(f"Linked data file is missing: {source_path}")
                    raw = parse_file(
                        source_path,
                        options=source.get("parser_options", {}),
                        expected_kind=kind,
                    )
                else:
                    raise ValueError(f"Unsupported source type: {kind or 'unknown'}")
                source_steps = source.get("transform_steps", [])
                if kind in {"odata", "web"} and raw.notices:
                    warnings.extend(
                        f"{source.get('name', source_id)}: {notice}"
                        for notice in raw.notices
                    )
                query_candidate = apply_transformations(raw, source_steps)
                type_map = column_types_after_steps(
                    raw.headers,
                    source_steps,
                    output_headers=query_candidate.headers,
                )
                loaded_candidates[source_id], calculated_types = self._apply_calculated_columns(
                    source_id, query_candidate, project=candidate,
                    column_types=type_map,
                )
                type_map.update(calculated_types)
                for table in candidate.get("model", {}).get("tables", []):
                    if table.get("id") == source_id or table.get("source_id") == source_id:
                        if table.get("column_types", {}) != type_map:
                            table["column_types"] = type_map
                            metadata_changed = True
            except (OSError, KeyError, TypeError, ValueError) as exc:
                if kind == "inline":
                    message = f"Could not load embedded table {source.get('name', source_id)}: {exc}"
                elif kind == "query":
                    message = f"Could not load query {source.get('name', source_id)}: {exc}"
                elif kind == "sql_server":
                    message = f"Could not load SQL Server table {source.get('name', source_id)}: {exc}"
                elif kind == "odata":
                    message = f"Could not load OData entity set {source.get('name', source_id)}: {exc}"
                elif kind == "web":
                    message = f"Could not load Web source {source.get('name', source_id)}: {exc}"
                elif kind not in SUPPORTED_SOURCE_KINDS:
                    message = f"The source type is unavailable for {source.get('name', source_id)}: {kind or 'unknown'}."
                elif kind == "folder":
                    message = f"Could not load linked data folder {source_path.name if source_path else source_id}: {exc}"
                else:
                    message = f"Could not load linked data file {source_path.name if source_path else source_id}: {exc}"
                load_errors[source_id] = message
                warnings.append(message)

        requested_active_id = candidate.get("active_source_id")
        active_source_id = requested_active_id
        model_loaded_ids = [
            str(source["id"])
            for source in sources
            if self._source_load_enabled(source)
            and str(source["id"]) in loaded_candidates
        ]
        if active_source_id not in model_loaded_ids:
            if model_loaded_ids:
                active_source_id = model_loaded_ids[0]
                candidate["active_source_id"] = active_source_id
                if requested_active_id in loaded_candidates:
                    warning = "The previous active query is excluded from model load; another loaded table was selected."
                elif requested_active_id is None:
                    warning = "No active table was saved; another loaded table was selected."
                else:
                    warning = "The previous active table was unavailable; another loaded table was selected."
            else:
                active_source_id = None
                candidate["active_source_id"] = None
                warning = "No model-loaded table is available in this project."
            if sources:
                warnings.append(warning)
                load_errors["__active_selection__"] = warning

        linked_source = next(
            (item for item in sources if item.get("id") == active_source_id),
            None,
        )
        active_source_path = source_paths.get(active_source_id) if active_source_id else None
        active_source_kind = str(linked_source.get("kind", "")) if linked_source else None
        active_parser_options = dict(linked_source.get("parser_options", {})) if linked_source else {}

        self._project = candidate
        self._project_path = path
        self._recovered_from_backup = recovered
        self._dirty = active_source_id != requested_active_id or metadata_changed
        self._current_view = candidate["active_view"]
        self._active_page_id = candidate["report"]["active_page_id"]
        self._selected_visual = ""
        self._field_query = ""
        self._current_region = None
        self._active_source_id = active_source_id
        self._active_source_path = active_source_path
        self._active_source_kind = active_source_kind
        self._active_parser_options = active_parser_options
        self._loaded_candidates = loaded_candidates
        self._source_load_errors = load_errors
        if active_source_id in loaded_candidates:
            self._install_source(
                active_source_path,
                active_source_id,
                loaded_candidates[active_source_id],
            )
        else:
            self._clear_source(clear_selection=False)
        self._source_warning = self._compose_source_warning()
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Opened {path.name}" + (" from recovery copy" if recovered else ""))

        if recovered:
            QMessageBox.warning(
                None,
                "Project recovered",
                "The project file was unreadable, so its last known-good backup was opened.\n\n"
                f"Saving will repair the project and keep the recovery copy at {path.name}.bak.",
            )
        if warnings:
            QMessageBox.warning(None, "Some project data is unavailable", "\n".join(warnings))
        return True

    def import_csv_dialog(self) -> None:
        self.import_data_dialog(expected_kind="csv")

    def import_excel_dialog(self) -> None:
        self.import_data_dialog(expected_kind="excel")

    def import_data_dialog(self, expected_kind: str | None = None) -> None:
        filters = {
            "csv": "CSV files (*.csv);;All files (*)",
            "excel": "Excel workbooks (*.xls *.xlsx *.xlsm);;All files (*)",
            "json": "JSON files (*.json);;All files (*)",
            "xml": "XML files (*.xml);;All files (*)",
            "parquet": "Parquet files (*.parquet);;All files (*)",
            "sqlite": "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)",
            None: (
                "Supported data files (*.csv *.xls *.xlsx *.xlsm *.json *.xml *.parquet *.db *.sqlite *.sqlite3);;"
                "CSV files (*.csv);;Excel workbooks (*.xls *.xlsx *.xlsm);;"
                "JSON files (*.json);;XML files (*.xml);;Parquet files (*.parquet);;"
                "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)"
            ),
        }
        title_kind = "SQLite" if expected_kind == "sqlite" else expected_kind.upper() if expected_kind else ""
        title = f"Import {title_kind} data" if title_kind else "Import data"
        path, _ = QFileDialog.getOpenFileName(None, title, "", filters[expected_kind])
        if path:
            self._import_file_path(Path(path), expected_kind=expected_kind)

    def import_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            None,
            "Choose folder to combine",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._import_folder_path(Path(folder))

    def import_folder_path(self, folder: Path) -> bool:
        return self._import_folder_path(Path(folder))

    def _import_folder_path(
        self,
        folder: Path,
        *,
        initial_options: dict[str, Any] | None = None,
    ) -> bool:
        folder = Path(folder).expanduser().resolve()
        if not folder.is_dir():
            QMessageBox.critical(None, "Folder unavailable", f"Choose an existing folder: {folder}")
            return False
        dialog = FolderImportDialog(
            folder,
            replacing=self._source_id_for_path(folder) is not None,
            initial_options=initial_options,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_import(folder, dialog.candidate)

    def import_csv_path(self, path: Path) -> bool:
        return self._import_file_path(path, expected_kind="csv")

    def import_excel_path(self, path: Path) -> bool:
        return self._import_file_path(path, expected_kind="excel")

    def import_data_path(self, path: Path) -> bool:
        return self._import_file_path(path)

    def _import_file_path(
        self,
        path: Path,
        expected_kind: str | None = None,
        initial_options: dict[str, Any] | None = None,
    ) -> bool:
        path = Path(path).expanduser().resolve()
        try:
            source_kind = kind_for_path(path)
            if expected_kind is not None and source_kind != expected_kind:
                expected_label = "SQLite" if expected_kind == "sqlite" else expected_kind.upper()
                raise ValueError(
                    f"Choose a {expected_label} file; this file has the {source_kind.upper()} extension."
                )
        except ValueError as exc:
            QMessageBox.critical(None, "Unsupported data file", str(exc))
            return False

        from analytics_studio.import_preview_dialog import FileImportPreviewDialog

        existing_sqlite_tables: set[str] = set()
        if source_kind == "sqlite":
            target = path.resolve()
            existing_sqlite_tables = {
                str(source.get("parser_options", {}).get("table_name"))
                for source in self._project.get("data_sources", [])
                if source.get("kind") == "sqlite"
                and source.get("path")
                and self._resolved_source_path(source) == target
                and isinstance(source.get("parser_options", {}).get("table_name"), str)
            }

        dialog = FileImportPreviewDialog(
            path,
            replacing=(
                self._source_id_for_path(path) is not None
                if source_kind != "sqlite"
                else False
            ),
            initial_options=initial_options,
            existing_sqlite_tables=existing_sqlite_tables,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_import(path, dialog.candidate)

    def _commit_import(self, path: Path, parsed: ImportCandidate) -> bool:
        path = Path(path).expanduser().resolve()
        existing_sources = list(self._project.get("data_sources", []))
        source_id = self._source_id_for_path(
            path,
            kind=parsed.kind,
            parser_options=parsed.options,
        ) or str(uuid4())
        existing_source = next(
            (source for source in existing_sources if source.get("id") == source_id),
            None,
        )
        transform_steps = list(existing_source.get("transform_steps", [])) if existing_source else []
        existing_table = next(
            (table for table in self._project.get("model", {}).get("tables", [])
             if table.get("id") == source_id or table.get("source_id") == source_id),
            None,
        )
        desired_table_name = (
            str(parsed.options.get("table_name", "")).strip()
            if parsed.kind == "sqlite"
            else path.stem
        )
        table_name = (
            str(existing_table.get("name"))
            if existing_table is not None
            else self._unique_table_name(desired_table_name)
        )
        source_record = {
            "id": source_id,
            "name": path.name,
            "kind": parsed.kind,
            "path": str(path),
            "parser_options": dict(parsed.options),
            "transform_steps": transform_steps,
        }
        updated_sources = []
        source_replaced = False
        for source in existing_sources:
            if source.get("id") == source_id:
                updated_sources.append({**source, **source_record})
                source_replaced = True
            else:
                updated_sources.append(source)
        if not source_replaced:
            updated_sources.append(source_record)
        next_project = deepcopy(self._project)
        next_project["data_sources"] = updated_sources
        next_project["active_source_id"] = source_id
        model = next_project.setdefault("model", {"tables": [], "relationships": []})
        tables = list(model.get("tables", []))
        table_record = {
            "id": source_id,
            "name": table_name,
            "source_id": source_id,
            "column_types": {header: "text" for header in parsed.headers},
        }
        table_replaced = False
        for index, table in enumerate(tables):
            if table.get("id") == source_id or table.get("source_id") == source_id:
                tables[index] = {**table, **table_record}
                table_replaced = True
                break
        if not table_replaced:
            tables.append(table_record)
        model["tables"] = tables

        try:
            source_candidate = apply_transformations(parsed, transform_steps)
            base_types = column_types_after_steps(
                parsed.headers, transform_steps, output_headers=source_candidate.headers
            )
            source_table = self._model_table_for_source(next_project, source_id)
            if source_table is not None:
                source_table["column_types"] = base_types
            source_candidate, calculated_types = self._apply_calculated_columns(
                source_id, source_candidate, project=next_project,
                column_types=base_types,
            )
            if source_table is not None:
                source_table["column_types"] = {
                    **base_types, **calculated_types
                }
            next_project = validate_project(next_project)
            dependent_candidates, dependent_types = self._rebuild_query_dependents(
                next_project, {source_id: source_candidate}
            )
            for dependent_id, type_map in dependent_types.items():
                dependent_table = next(
                    (table for table in next_project["model"]["tables"]
                     if table.get("id") == dependent_id
                     or table.get("source_id") == dependent_id),
                    None,
                )
                if dependent_table is not None:
                    dependent_table["column_types"] = type_map
            next_project = validate_project(next_project)
        except (ProjectFileError, QueryError, OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(None, "Could not import data", str(exc))
            return False

        # Publish the fully prepared project and its matching table only after every
        # parser and project invariant has passed.
        self._project = next_project
        self._active_source_id = source_id
        self._active_source_path = path
        self._active_source_kind = parsed.kind
        self._active_parser_options = dict(parsed.options)
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._loaded_candidates.update(dependent_candidates)
        for updated_id in dependent_candidates:
            self._source_load_errors.pop(updated_id, None)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._install_source(path, source_id, source_candidate)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Loaded {path.name} · {parsed.row_count:,} rows")
        try:
            self._recent_source_store.add(
                path, parsed.kind, parsed.options, display_name=path.name
            )
        except (OSError, TypeError, ValueError) as exc:
            self._set_status(
                f"Loaded {path.name} · {parsed.row_count:,} rows; recent history could not be saved: {exc}"
            )
        else:
            self.stateChanged.emit()
        return True

    def enter_data_dialog(self, use_clipboard: bool = False) -> bool:
        initial_text = QApplication.clipboard().text() if use_clipboard else ""
        dialog = EnterDataDialog(
            replacing=False,
            initial_text=initial_text,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_inline(dialog.candidate)

    def load_sample_data(self) -> bool:
        return self._commit_inline(sample_candidate())

    def _commit_inline(self, parsed: ImportCandidate) -> bool:
        if not isinstance(parsed, ImportCandidate) or parsed.kind != "inline":
            self._set_status("The entered table is invalid.")
            return False
        source_id = str(uuid4())
        source_name = str(parsed.options.get("name", "Entered data")).strip() or "Entered data"
        table_name = self._unique_table_name(source_name)
        try:
            source_record = source_from_candidate(parsed, source_id, source_name)
            source_record["transform_steps"] = []
            next_project = deepcopy(self._project)
            sources = list(next_project.get("data_sources", []))
            for index, item in enumerate(sources):
                if item.get("id") == source_id:
                    sources[index] = source_record
                    break
            else:
                sources.append(source_record)
            next_project["data_sources"] = sources
            next_project["active_source_id"] = source_id

            table_record = {
                "id": source_id,
                "name": table_name,
                "source_id": source_id,
                "column_types": {header: "text" for header in parsed.headers},
            }
            tables = list(next_project.get("model", {}).get("tables", []))
            for index, table in enumerate(tables):
                if table.get("id") == source_id or table.get("source_id") == source_id:
                    tables[index] = {**table, **table_record}
                    break
            else:
                tables.append(table_record)
            next_project["model"]["tables"] = tables
            next_project = validate_project(next_project)
        except (ProjectFileError, TypeError, ValueError) as exc:
            self._set_status(f"Could not create table: {exc}")
            return False

        self._project = next_project
        self._active_source_id = source_id
        self._active_source_path = None
        self._active_source_kind = "inline"
        self._active_parser_options = {}
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._install_source(None, source_id, parsed)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Loaded {table_name} · {len(self._rows):,} rows")
        return True

    def append_queries_dialog(self) -> bool:
        """Create a saved append query from two loaded tables."""
        available = [
            dict(table) for table in self._table_catalog
            if table.get("evaluated") and table.get("sourceId") in self._loaded_candidates
        ]
        if len(available) < 2:
            self._set_status("Load at least two tables before appending queries.")
            return False
        candidates = {
            str(table["sourceId"]): self._loaded_candidates[str(table["sourceId"])]
            for table in available
        }
        dialog = AppendQueriesDialog(available, candidates)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        query_name = dialog.query_name
        if not query_name or "\x00" in query_name:
            self._set_status("Enter a valid name for the appended query.")
            return False

        source_ids = dialog.source_ids
        tables_by_source = {
            str(table.get("source_id") or table.get("id")): table
            for table in self._project.get("model", {}).get("tables", [])
        }
        first_types = tables_by_source.get(source_ids[0], {}).get("column_types", {})
        second_types = tables_by_source.get(source_ids[1], {}).get("column_types", {})
        output_types = {
            header: first_types.get(header, "text")
            if first_types.get(header, "text") == second_types.get(header, "text")
            else "text"
            for header in dialog.candidate.headers
        }
        return self._create_saved_query(
            query_name,
            source_ids,
            dialog.candidate,
            {"operation": "append", "source_ids": source_ids},
            output_types,
        )

    def merge_queries_dialog(self) -> bool:
        """Create a saved query by joining two loaded tables on one or more keys."""
        available = [
            dict(table) for table in self._table_catalog
            if table.get("evaluated") and table.get("sourceId") in self._loaded_candidates
        ]
        if len(available) < 2:
            self._set_status("Load at least two tables before merging queries.")
            return False
        candidates = {
            str(table["sourceId"]): self._loaded_candidates[str(table["sourceId"])]
            for table in available
        }
        dialog = MergeQueriesDialog(available, candidates)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        definition = dialog.query_definition
        source_ids = list(definition.get("source_ids", []))
        query_name = dialog.query_name
        if not query_name or "\x00" in query_name:
            self._set_status("Enter a valid name for the merged query.")
            return False

        tables_by_source = {
            str(table.get("source_id") or table.get("id")): table
            for table in self._project.get("model", {}).get("tables", [])
        }
        output_types: dict[str, str] = {}
        column_sources = dialog.candidate.options.get("column_sources", {})
        for output_column, origin in column_sources.items():
            source_id = source_ids[0] if origin.get("side") == "left" else source_ids[1]
            source_types = tables_by_source.get(source_id, {}).get("column_types", {})
            output_types[output_column] = source_types.get(origin.get("column", ""), "text")
        return self._create_saved_query(
            query_name,
            source_ids,
            dialog.candidate,
            definition,
            output_types,
        )

    def _create_saved_query(
        self,
        query_name: str,
        source_ids: list[str],
        candidate: ImportCandidate,
        definition: dict[str, Any],
        output_types: dict[str, str],
    ) -> bool:
        """Commit a derived query only after its definition and result validate."""
        if not query_name.strip() or "\x00" in query_name:
            self._set_status("Enter a valid name for the query.")
            return False
        source_id = str(uuid4())
        table_name = self._unique_table_name(query_name)
        query_steps = [
            {"op": "convert_type", "column": header, "type": output_types.get(header, "text")}
            for header in candidate.headers
            if output_types.get(header, "text") != "text"
        ]
        try:
            validated_steps = validate_steps(query_steps)
            transformed = apply_transformations(candidate, validated_steps)
            source_record = {
                "id": source_id,
                "name": table_name,
                "kind": "query",
                "load_enabled": True,
                "include_in_report_refresh": True,
                "query_definition": deepcopy(definition),
                "transform_steps": validated_steps,
            }
            table_record = {
                "id": source_id,
                "name": table_name,
                "source_id": source_id,
                "column_types": column_types_after_steps(
                    candidate.headers,
                    validated_steps,
                    output_headers=transformed.headers,
                ),
            }
            if definition.get("operation") in {"calendar", "calendar_auto"}:
                table_record["date_column"] = "Date"
            next_project = deepcopy(self._project)
            next_project["data_sources"].append(source_record)
            next_project["model"]["tables"].append(table_record)
            next_project["active_source_id"] = source_id
            next_project = validate_project(next_project)
        except (ProjectFileError, QueryError, TypeError, ValueError) as exc:
            operation = str(definition.get("operation", "query"))
            label = "calculated table" if operation == "calculated_table" else f"{operation} query"
            self._set_status(f"Could not create {label}: {exc}")
            return False

        self._project = next_project
        self._loaded_candidates[source_id] = transformed
        self._active_source_id = source_id
        self._active_source_path = None
        self._active_source_kind = "query"
        self._active_parser_options = {}
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._install_source(None, source_id, transformed)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Created {table_name} · {len(transformed.rows):,} rows")
        return True

    def transform_data_dialog(self) -> bool:
        if not self.sourceLoaded or self._active_source_id is None:
            self._set_status("Load a table before transforming data.")
            return False
        source = next(
            (item for item in self._project["data_sources"]
             if item.get("id") == self._active_source_id),
            None,
        )
        if source is None:
            self._set_status("The active data source record is unavailable.")
            return False
        try:
            raw_candidate = self._raw_candidate_for_source(source)
            steps = validate_steps(source.get("transform_steps", []))
            dialog = TransformDataDialog(raw_candidate, steps)
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not open Transform data: {exc}")
            QMessageBox.critical(None, "Could not transform data", str(exc))
            return False
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_transform_steps(
            source["id"], dialog.steps or [], dialog.candidate, previewed_source=raw_candidate
        )

    @Slot(result=bool)
    def calculated_table_dialog(self) -> bool:
        """Create a saved DISTINCT calculated table from one loaded model column."""
        tables = [
            dict(table) for table in self._table_catalog
            if table.get("loaded") and table.get("loadEnabled")
            and str(table.get("sourceId", "")) in self._loaded_candidates
        ]
        if not tables:
            self._set_status("Load a model table before creating a calculated table.")
            return False
        candidates = {
            str(table["sourceId"]): self._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = CalculatedTableDialog(tables, candidates)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._create_saved_query(
            dialog.query_name,
            dialog.source_ids,
            dialog.candidate,
            dialog.query_definition,
            dialog.output_types,
        )

    @Slot(result=bool)
    def calendar_table_dialog(self) -> bool:
        """Create a fixed or model-driven, marked calendar table."""
        tables = [
            dict(table) for table in self._table_catalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): self._loaded_candidates[str(table["sourceId"])]
            for table in tables
            if str(table.get("sourceId", "")) in self._loaded_candidates
        }
        dialog = CalendarTableDialog(tables, candidates)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._create_saved_query(
            dialog.query_name,
            dialog.source_ids,
            dialog.candidate,
            dialog.query_definition,
            dialog.output_types,
        )

    @Slot(result=bool)
    def mark_date_table_dialog(self) -> bool:
        """Mark or unmark a loaded Date/DateTime model column as a date table."""
        tables = [
            dict(table) for table in self._table_catalog
            if table.get("loaded") and table.get("loadEnabled")
            and str(table.get("sourceId", "")) in self._loaded_candidates
        ]
        if not tables:
            self._set_status("Load a model table before marking a date table.")
            return False
        candidates = {
            str(table["sourceId"]): self._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = DateTableDialog(tables, candidates)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.action:
            return False
        source_id = dialog.source_id
        target = self._model_table_for_source(self._project, source_id)
        if target is None:
            self._set_status("The selected model table is unavailable.")
            return False

        next_project = deepcopy(self._project)
        next_target = self._model_table_for_source(next_project, source_id)
        if next_target is None:
            self._set_status("The selected model table is unavailable.")
            return False
        if dialog.action == "clear":
            next_target["date_column"] = None
        else:
            candidate = candidates.get(source_id)
            date_column = dialog.date_column
            column_type = str(target.get("column_types", {}).get(date_column, ""))
            try:
                if candidate is None:
                    raise DateTableError("The selected model table is not loaded.")
                validate_date_table_rows(candidate.rows, date_column, column_type)
                next_target["date_column"] = date_column
            except DateTableError as exc:
                self._set_status(f"Could not mark date table: {exc}")
                return False

        try:
            next_project = validate_project(next_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not update date table: {exc}")
            return False
        self._project = next_project
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        if dialog.action == "clear":
            self._set_status(f"Cleared the date-table mark on {target['name']}.")
        else:
            self._set_status(
                f"Marked {target['name']}[{dialog.date_column}] as the date table."
            )
        return True

    def new_measure_dialog(self) -> bool:
        return self._measure_dialog(quick=False)

    def quick_measure_dialog(self) -> bool:
        return self._measure_dialog(quick=True)

    @Slot(result=bool)
    def calculated_column_dialog(self) -> bool:
        """Create, edit, or remove a local DAX calculated column."""
        source_id = self._active_source_id
        if not self.sourceLoaded or source_id is None:
            self._set_status("Load a table before creating a calculated column.")
            return False
        table = self._model_table_for_source(self._project, source_id)
        source = next((
            item for item in self._project.get("data_sources", [])
            if item.get("id") == source_id
        ), None)
        if table is None or source is None:
            self._set_status("The active model table is unavailable.")
            return False
        dialog = CalculatedColumnDialog(table.get("calculated_columns", []))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False

        next_project = deepcopy(self._project)
        next_table = self._model_table_for_source(next_project, source_id)
        if next_table is None:
            self._set_status("The active model table is unavailable.")
            return False
        current = list(next_table.get("calculated_columns", []))
        if dialog.action == "delete":
            current = [
                item for item in current
                if item["name"].casefold() != dialog.original_name.casefold()
            ]
        else:
            definition = dialog.column
            if definition is None:
                return False
            replaced = False
            updated = []
            for item in current:
                if item["name"].casefold() == dialog.original_name.casefold():
                    updated.append(definition)
                    replaced = True
                else:
                    updated.append(item)
            current = updated if replaced else [*current, definition]

        try:
            next_table["calculated_columns"] = validate_calculated_columns(current)
            raw_candidate = self._raw_candidate_for_source(source)
            query_candidate = apply_transformations(
                raw_candidate, source.get("transform_steps", [])
            )
            base_types = column_types_after_steps(
                raw_candidate.headers,
                source.get("transform_steps", []),
                output_headers=query_candidate.headers,
            )
            calculated_candidate, calculated_types = self._apply_calculated_columns(
                source_id, query_candidate, project=next_project,
                column_types=base_types,
            )
            next_table["column_types"] = {**base_types, **calculated_types}
            next_project = validate_project(next_project)
        except (
            MeasureError, ProjectFileError, QueryError, OSError, TypeError, ValueError
        ) as exc:
            self._set_status(f"Could not update calculated column: {exc}")
            QMessageBox.warning(None, "Could not update calculated column", str(exc))
            return False

        self._project = next_project
        self._loaded_candidates[source_id] = calculated_candidate
        if source_id == self._active_source_id:
            self._install_source(self._active_source_path, source_id, calculated_candidate)
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        action_label = "Removed" if dialog.action == "delete" else "Saved"
        self._set_status(f"{action_label} calculated column on {table['name']}")
        return True

    def _measure_dialog(self, *, quick: bool) -> bool:
        if not self.sourceLoaded:
            self._set_status("Import a table before creating a measure.")
            return False
        measures = self._project.get("model", {}).get("measures", [])
        dialog = MeasureDialog(
            list(self._headers),
            [str(item["name"]) for item in measures],
            quick=quick,
            default_column=(
                _report_field(self._headers, "revenue")
                or next((
                    header for header in self._headers
                    if any(_report_number(row.get(header, "")) is not None for row in self._rows)
                ), None)
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.measure is None:
            return False
        return self.create_measure(dialog.measure["name"], dialog.measure["expression"])

    def create_measure(self, name: str, expression: str) -> bool:
        """Validate, evaluate, then transactionally add a local DAX measure."""
        if not self.sourceLoaded:
            self._set_status("Import a table before creating a measure.")
            return False
        try:
            measure = normalize_measure(name, expression)
            current = list(self._project.get("model", {}).get("measures", []))
            if any(item["name"].casefold() == measure["name"].casefold() for item in current):
                raise MeasureError(f"A measure named {measure['name']!r} already exists.")
            if len(current) >= MAX_MEASURES:
                raise MeasureError(f"A model can contain at most {MAX_MEASURES} measures.")
            candidate_measures = [*current, measure]
            table_name = self._active_model_table_name()
            filtered_rows_by_table, measure_table_context, filter_table_ids = (
                self._report_filter_context()
            )
            active_table_id = self._active_model_table_id()
            filtered_rows = filtered_rows_by_table.get(active_table_id, list(self._rows))
            evaluate_measures(
                candidate_measures, filtered_rows, self._headers,
                table_name, measure_names=[measure["name"]],
                table_context=measure_table_context,
                relationships=self._project.get("model", {}).get("relationships", []),
                filter_table_ids=filter_table_ids,
                active_table_id=active_table_id or None,
            )
            next_project = deepcopy(self._project)
            next_project.setdefault("model", {}).setdefault("measures", []).append(measure)
            page = next(
                page for page in next_project["report"]["pages"]
                if page["id"] == next_project["report"]["active_page_id"]
            )
            visual_name = f"{measure['name']} KPI"
            if not any(isinstance(v, dict) and v.get("title") == visual_name for v in page.get("visuals", [])):
                from uuid import uuid4
                page.setdefault("visuals", []).append({
                    "id": str(uuid4()), "type": "card", "title": visual_name,
                    "x": 10, "y": 10, "width": 120, "height": 80
                })
            next_project = validate_project(next_project)
        except (MeasureError, ProjectFileError, StopIteration, TypeError, ValueError) as exc:
            self._set_status(f"Could not create measure: {exc}")
            return False

        self._project = next_project
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        value = self._measure_values.get(measure["name"], "—")
        self._set_status(f"Created measure {measure['name']} = {value}")
        return True

    def _active_model_table_name(self) -> str:
        table = next(
            (item for item in self._project.get("model", {}).get("tables", [])
             if item.get("id") == self._active_source_id or item.get("source_id") == self._active_source_id),
            None,
        )
        return str(table.get("name", "")) if table else self.sourceName

    def _active_model_table_id(self) -> str:
        table = next(
            (item for item in self._table_catalog
             if item.get("sourceId") == self._active_source_id),
            None,
        )
        return str(table.get("id", "")) if table else ""

    @staticmethod
    def _model_table_for_source(
        project: dict[str, Any], source_id: str
    ) -> dict[str, Any] | None:
        return next((
            table for table in project.get("model", {}).get("tables", [])
            if table.get("id") == source_id or table.get("source_id") == source_id
        ), None)

    def _apply_calculated_columns(
        self,
        source_id: str,
        candidate: ImportCandidate,
        *,
        project: dict[str, Any] | None = None,
        column_types: dict[str, str] | None = None,
    ) -> tuple[ImportCandidate, dict[str, str]]:
        """Materialize model calculations after query steps for one table."""
        document = project or self._project
        table = self._model_table_for_source(document, source_id)
        if table is None:
            return candidate, {}
        effective_types = dict(table.get("column_types", {}))
        if column_types is not None:
            effective_types.update(column_types)
        definitions = table.get("calculated_columns", [])
        if definitions:
            headers, rows, type_map = evaluate_calculated_columns(
                definitions,
                candidate.rows,
                candidate.headers,
                str(table.get("name", "")),
            )
            candidate = ImportCandidate(
                kind=candidate.kind,
                headers=headers,
                rows=rows,
                options=dict(candidate.options),
                notices=list(candidate.notices),
            )
        else:
            type_map = {}
        effective_types.update(type_map)
        date_column = table.get("date_column")
        if date_column is not None:
            if date_column not in candidate.headers:
                raise DateTableError(
                    f"Marked date column {date_column!r} is no longer present in "
                    f"{table.get('name', 'the model table')!r}."
                )
            column_type = str(effective_types.get(date_column, ""))
            validate_date_table_rows(candidate.rows, str(date_column), column_type)
        return candidate, type_map

    def _measure_table_context(
        self,
        filter_rows_by_table: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        filter_rows_by_table = filter_rows_by_table or {}
        context = []
        for table in self._table_catalog:
            if not (table.get("loaded") and table.get("loadEnabled")):
                continue
            source_id = str(table.get("sourceId", ""))
            candidate = self._loaded_candidates.get(source_id)
            if candidate is None:
                continue
            table_id = str(table.get("id", ""))
            context.append({
                "id": table_id,
                "name": str(table.get("name", table_id)),
                "headers": list(candidate.headers),
                "rows": candidate.rows,
                "column_types": dict(table.get("columnTypes", {})),
                "date_column": str(table.get("dateColumn") or ""),
                "filter_column_rows": {},
                "filter_column_blank_allowed": {},
                "filter_context_complete": True,
                **({"filter_rows": filter_rows_by_table[table_id]}
                   if table_id in filter_rows_by_table else {}),
            })
        return context

    def _active_column_type_map(self) -> dict[str, str]:
        table = next(
            (item for item in self._project.get("model", {}).get("tables", [])
             if item.get("id") == self._active_source_id or item.get("source_id") == self._active_source_id),
            None,
        )
        stored = table.get("column_types", {}) if table else {}
        if not isinstance(stored, dict):
            return {}
        return {str(column): str(type_name) for column, type_name in stored.items()}

    def _report_filter_context(
        self,
        visual_name: str | None = None,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], set[str]]:
        """Build page context plus optional filters for one report visual."""
        self._region_column = _report_field(self._headers, "region") if self.sourceLoaded else None
        conditions: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        active_table_id = self._active_model_table_id()
        if self._current_region is not None and self._region_column and active_table_id:
            conditions[active_table_id].append((
                self._region_column,
                {
                    "clauses": [{"operator": "equals", "value": self._current_region}],
                    "logic": "and",
                },
            ))

        page = self._active_page()
        saved_report_filters = self._project.get("report", {}).get("filters", [])
        saved_page_filters = page.get("filters", []) if page else []
        saved_visual_filters = [
            visual_filter for visual_filter in (page.get("visual_filters", []) if page else [])
            if visual_name is not None and visual_filter.get("visual_name") == visual_name
        ]
        for report_filter in saved_report_filters:
            table_id = str(report_filter.get("table_id", ""))
            column = str(report_filter.get("column", ""))
            conditions[table_id].append((column, report_filter))
        for page_filter in saved_page_filters:
            table_id = str(page_filter.get("table_id", ""))
            column = str(page_filter.get("column", ""))
            conditions[table_id].append((column, page_filter))
        for visual_filter in saved_visual_filters:
            if any(
                clause.get("operator") == _REPORT_FILTER_TOP_N
                for clause in visual_filter.get("clauses", [])
            ):
                continue
            table_id = str(visual_filter.get("table_id", ""))
            column = str(visual_filter.get("column", ""))
            conditions[table_id].append((column, visual_filter))

        context = self._measure_table_context()
        contexts_by_id = {str(table["id"]): table for table in context}
        saved_filters = [*saved_report_filters, *saved_page_filters, *saved_visual_filters]
        def filter_references_unavailable_field(report_filter: dict[str, Any]) -> bool:
            table_id = str(report_filter.get("table_id", ""))
            table = contexts_by_id.get(table_id)
            if table is None or str(report_filter.get("column", "")) not in table["headers"]:
                return True
            for clause in report_filter.get("clauses", []):
                if clause.get("operator") != _REPORT_FILTER_TOP_N:
                    continue
                order_by = clause.get("order_by", {})
                order_table_id = str(order_by.get("table_id", ""))
                order_table = contexts_by_id.get(order_table_id)
                if order_table is None or str(order_by.get("column", "")) not in order_table["headers"]:
                    return True
            return False

        has_unavailable_filter = any(
            filter_references_unavailable_field(report_filter)
            for report_filter in saved_filters
        )
        has_incompatible_relative_date = False
        has_incompatible_relative_time = False
        has_unsupported_top_n_filter = False
        for report_filter in saved_filters:
            table_id = str(report_filter.get("table_id", ""))
            column = str(report_filter.get("column", ""))
            table = contexts_by_id.get(table_id)
            if (
                table is not None
                and column in table["headers"]
                and str(table.get("column_types", {}).get(column, "text")) != "date"
                and _report_filter_has_relative_date(report_filter)
            ):
                has_incompatible_relative_date = True
            if (
                table is not None
                and column in table["headers"]
                and str(table.get("column_types", {}).get(column, "text")) != "datetime"
                and _report_filter_has_relative_time(report_filter)
            ):
                has_incompatible_relative_time = True
            for clause in report_filter.get("clauses", []):
                if clause.get("operator") != _REPORT_FILTER_TOP_N:
                    continue
                order_by = clause.get("order_by", {})
                order_table_id = str(order_by.get("table_id", ""))
                order_table = contexts_by_id.get(order_table_id)
                expected_region = _report_field(table["headers"], "region") if table else None
                if (
                    visual_name != "Region revenue"
                    or table_id != active_table_id
                    or column != expected_region
                    or order_table_id != active_table_id
                    or order_table is None
                    or str(order_by.get("column", "")) not in order_table["headers"]
                ):
                    has_unsupported_top_n_filter = True
        filter_messages = []
        if has_unavailable_filter:
            filter_messages.append(
                "A saved filter refers to a field that is not currently loaded; it is ignored."
            )
        if has_incompatible_relative_date:
            filter_messages.append(
                "Saved relative-date filters need Date-typed fields; those rules are ignored."
            )
        if has_incompatible_relative_time:
            filter_messages.append(
                "Saved relative-time filters need Date/time-typed fields; those rules are ignored."
            )
        if has_unsupported_top_n_filter:
            filter_messages.append(
                "Saved Top N filters apply only to the active table's Region revenue chart fields; unsupported rules are ignored."
            )
        unavailable_message = " ".join(filter_messages)
        filter_table_ids: set[str] = set()
        explicit_rows: dict[str, list[dict[str, Any]]] = {}
        for table_id, table_conditions in conditions.items():
            table = contexts_by_id.get(table_id)
            if table is None or any(column not in table["headers"] for column, _ in table_conditions):
                continue
            compiled_conditions = []
            for column, report_filter in table_conditions:
                column_type = str(table.get("column_types", {}).get(column, "text"))
                if column_type != "date" and _report_filter_has_relative_date(report_filter):
                    continue
                if column_type != "datetime" and _report_filter_has_relative_time(report_filter):
                    continue
                compiled_conditions.append((
                    column,
                    _compile_report_filter(
                        report_filter,
                        column_type,
                        self._relative_filter_anchor_date,
                        self._relative_filter_anchor_time,
                    ),
                ))
            if not compiled_conditions:
                continue
            filtered_rows = [
                row for row in table["rows"]
                if all(_report_filter_matches(
                    row.get(column), report_filter,
                    str(table.get("column_types", {}).get(column, "text")),
                ) for column, report_filter in compiled_conditions)
            ]
            table["filter_rows"] = filtered_rows
            table["filter_column_rows"] = {
                column: [
                    row_index
                    for row_index, row in enumerate(table["rows"])
                    if all(
                        _report_filter_matches(
                            row.get(filtered_column), report_filter,
                            str(table.get("column_types", {}).get(filtered_column, "text")),
                        )
                        for filtered_column, report_filter in compiled_conditions
                        if filtered_column == column
                    )
                ]
                for column, _report_filter in compiled_conditions
            }
            table["filter_column_blank_allowed"] = {
                column: all(
                    _report_filter_matches(
                        "", report_filter,
                        str(table.get("column_types", {}).get(column, "text")),
                    )
                    for filtered_column, report_filter in compiled_conditions
                    if filtered_column == column
                )
                for column, _report_filter in compiled_conditions
            }
            explicit_rows[table_id] = filtered_rows
            filter_table_ids.add(table_id)

        if not filter_table_ids:
            rows_by_id = {table_id: list(table["rows"]) for table_id, table in contexts_by_id.items()}
            self._filter_context_error = unavailable_message
            return rows_by_id, context, filter_table_ids

        try:
            rows_by_id = propagate_relationship_filters(
                context,
                self._project.get("model", {}).get("relationships", []),
                filter_table_ids,
            )
            self._filter_context_error = unavailable_message
        except RelationshipError as exc:
            self._filter_context_error = " ".join(
                message for message in (unavailable_message, str(exc)) if message
            )
            rows_by_id = {
                table_id: explicit_rows.get(table_id, list(table["rows"]))
                for table_id, table in contexts_by_id.items()
            }
        return rows_by_id, context, filter_table_ids

    def _raw_candidate_for_source(self, source: dict[str, Any]) -> ImportCandidate:
        if source.get("kind") == "inline":
            headers = list(source["headers"])
            rows = [
                {
                    header: "" if row[header] is None else str(row[header])
                    for header in headers
                }
                for row in source["rows"]
            ]
            return ImportCandidate("inline", headers, rows, {"name": source["name"]}, [])
        if source.get("kind") == "query":
            return self._query_candidate(
                source, self._loaded_candidates, project=self._project
            )
        if source.get("kind") == "sql_server":
            return self._sql_server_candidate_for_source(source)
        if source.get("kind") == "odata":
            return self._odata_candidate_for_source(source)
        if source.get("kind") == "web":
            return self._web_candidate_for_source(source)
        path = self._resolved_source_path(source)
        if source.get("kind") == "folder":
            return parse_folder(path, options=source.get("parser_options", {}))
        return parse_file(
            path,
            options=source.get("parser_options", self._active_parser_options),
            expected_kind=source.get("kind"),
        )

    def _sql_server_candidate_for_source(self, source: dict[str, Any]) -> ImportCandidate:
        connection = dict(source.get("connection", {}))
        credential_ref = str(connection.get("credential_ref", ""))
        password = self._sql_server_passwords.get(credential_ref)
        prompted = False
        if not password:
            try:
                password = get_sql_server_password(credential_ref)
            except CredentialStoreError as exc:
                raise SQLServerError(str(exc)) from exc
        if not password:
            password, accepted = QInputDialog.getText(
                None,
                "SQL Server credentials required",
                f"Password for {connection.get('username', 'SQL Server user')} "
                f"on {connection.get('server', 'server')}/{connection.get('database', 'database')}:",
                QLineEdit.EchoMode.Password,
            )
            if not accepted or not password:
                raise SQLServerError("A SQL Server password is required to load this table.")
            prompted = True
        candidate = read_sql_server_object(
            connection,
            dict(source.get("parser_options", {})),
            password,
        )
        if prompted:
            try:
                set_sql_server_password(credential_ref, password)
            except CredentialStoreError as exc:
                raise SQLServerError(str(exc)) from exc
        self._sql_server_passwords[credential_ref] = password
        return candidate

    @staticmethod
    def _odata_candidate_for_source(source: dict[str, Any]) -> ImportCandidate:
        return read_odata_entity_set(
            dict(source.get("connection", {})),
            dict(source.get("parser_options", {})),
        )

    @staticmethod
    def _web_candidate_for_source(source: dict[str, Any]) -> ImportCandidate:
        return read_web_source(
            dict(source.get("connection", {})),
            dict(source.get("parser_options", {})),
        )

    @staticmethod
    def _query_candidate(
        source: dict[str, Any],
        candidates: dict[str, ImportCandidate],
        *,
        project: dict[str, Any] | None = None,
    ) -> ImportCandidate:
        definition = source.get("query_definition", {})
        source_ids = definition.get("source_ids", [])
        try:
            inputs = [candidates[source_id] for source_id in source_ids]
        except KeyError as exc:
            raise QueryError(
                f"Query source {exc.args[0]!r} is not currently available."
            ) from exc
        operation = definition.get("operation")
        if operation == "append":
            return append_candidates(inputs)
        if operation == "merge" and len(inputs) == 2:
            return merge_candidates(
                inputs[0],
                inputs[1],
                left_keys=definition.get("left_keys", []),
                right_keys=definition.get("right_keys", []),
                join_kind=definition.get("join_kind", ""),
                right_name=definition.get("right_name", "Right"),
            )
        if operation == "calculated_table" and len(inputs) == 1:
            headers, rows = evaluate_calculated_table(
                definition.get("expression"),
                inputs[0],
                definition.get("source_table"),
            )
            return ImportCandidate(
                kind="query", headers=headers, rows=rows, options={}, notices=[]
            )
        if operation == "calendar":
            return generate_calendar(
                definition.get("start_date"), definition.get("end_date")
            )
        if operation == "calendar_auto":
            table_by_source = {
                str(table.get("source_id") or table.get("id")): table
                for table in (project or {}).get("model", {}).get("tables", [])
            }
            date_columns: list[dict[str, str]] = []
            for source_id in source_ids:
                table = table_by_source.get(source_id)
                if table is None:
                    continue
                calculated = {
                    str(item.get("name"))
                    for item in table.get("calculated_columns", [])
                }
                for column, column_type in table.get("column_types", {}).items():
                    if column_type in {"date", "datetime"} and column not in calculated:
                        date_columns.append({
                            "source_id": source_id,
                            "column": str(column),
                            "type": str(column_type),
                        })
            return generate_calendar_auto(
                dict(zip(source_ids, inputs)),
                date_columns,
                definition.get("fiscal_year_end_month", 12),
            )
        raise QueryError(f"Unsupported saved query operation: {operation!r}.")

    @staticmethod
    def _source_load_enabled(source: dict[str, Any]) -> bool:
        """Return whether a saved source participates in the model tables."""
        return source.get("kind") != "query" or source.get("load_enabled", True) is True

    @staticmethod
    def _source_refresh_included(source: dict[str, Any]) -> bool:
        """Return whether a saved query participates in report refresh."""
        return (
            source.get("kind") != "query"
            or source.get("include_in_report_refresh", True) is True
        )

    @classmethod
    def _source_is_refresh_root(cls, source: dict[str, Any]) -> bool:
        """Return whether a source should refresh independently in Refresh All."""
        kind = source.get("kind")
        if kind == "query":
            return cls._source_refresh_included(source)
        if kind in {"sql_server", "odata", "web"}:
            return True
        return kind in SUPPORTED_SOURCE_KINDS - {"inline", "query"} and bool(
            source.get("path")
        )

    @staticmethod
    def _source_dependency_order(
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return sources before the append queries that depend on them."""
        sources_by_id = {str(source["id"]): source for source in sources}
        ordered: list[dict[str, Any]] = []
        visited: set[str] = set()

        def visit(source_id: str) -> None:
            if source_id in visited:
                return
            source = sources_by_id[source_id]
            if source.get("kind") == "query":
                for dependency in source["query_definition"]["source_ids"]:
                    visit(dependency)
            visited.add(source_id)
            ordered.append(source)

        for source in sources:
            visit(str(source["id"]))
        return ordered

    def _rebuild_query_dependents(
        self,
        project: dict[str, Any],
        base_candidates: dict[str, ImportCandidate],
    ) -> tuple[dict[str, ImportCandidate], dict[str, dict[str, str]]]:
        """Re-evaluate included queries downstream of changed candidates."""
        candidates = dict(self._loaded_candidates)
        candidates.update(base_candidates)
        updates = dict(base_candidates)
        type_maps: dict[str, dict[str, str]] = {}
        for source in self._source_dependency_order(project.get("data_sources", [])):
            if source.get("kind") != "query":
                continue
            source_id = str(source["id"])
            dependencies = source["query_definition"]["source_ids"]
            if source_id in updates or not any(item in updates for item in dependencies):
                continue
            if not self._source_refresh_included(source):
                previous = candidates.get(source_id)
                if previous is None:
                    raise QueryError(
                        f"Cannot refresh dependent query {source.get('name', source_id)!r}: "
                        "it is excluded from report refresh and has no cached result. "
                        "Include it in report refresh and try again."
                    )
                # Preserve this query's last evaluated data, then let included
                # downstream queries continue from that saved in-memory result.
                updates[source_id] = previous
                continue
            if not all(item in candidates for item in dependencies):
                continue
            raw = self._query_candidate(source, candidates, project=project)
            query_candidate = apply_transformations(raw, source.get("transform_steps", []))
            type_map = column_types_after_steps(
                raw.headers,
                source.get("transform_steps", []),
                output_headers=query_candidate.headers,
            )
            transformed, calculated_types = self._apply_calculated_columns(
                source_id, query_candidate, project=project,
                column_types=type_map,
            )
            candidates[source_id] = transformed
            updates[source_id] = transformed
            type_maps[source_id] = type_map
            type_maps[source_id].update(calculated_types)
        return updates, type_maps

    def _resolved_source_path(self, source: dict[str, Any]) -> Path:
        stored_path = str(source["path"])
        if self._project_path is not None:
            return resolve_source_path(stored_path, self._project_path)
        return Path(stored_path).expanduser().resolve()

    def _commit_transform_steps(
        self,
        source_id: str,
        steps: list[dict[str, str]],
        transformed: ImportCandidate,
        *,
        previewed_source: ImportCandidate | None = None,
    ) -> bool:
        try:
            validated_steps = validate_steps(steps)
            source = next(
                item for item in self._project["data_sources"]
                if item.get("id") == source_id
            )
            raw_candidate = self._raw_candidate_for_source(source)
            if previewed_source is not None and raw_candidate != previewed_source:
                self._set_status(
                    "The source changed while Transform data was open. Reopen Transform data to preview the latest rows."
                )
                return False
            confirmed = apply_transformations(raw_candidate, validated_steps)
            if confirmed != transformed:
                self._set_status(
                    "The transformation result no longer matches its preview. Reopen Transform data and try again."
                )
                return False
            next_project = deepcopy(self._project)
            target = next(
                item for item in next_project["data_sources"]
                if item.get("id") == source_id
            )
            target["transform_steps"] = validated_steps
            type_map = column_types_after_steps(
                raw_candidate.headers,
                validated_steps,
                output_headers=confirmed.headers,
            )
            calculated_candidate, calculated_types = self._apply_calculated_columns(
                source_id, confirmed, project=next_project,
                column_types=type_map,
            )
            type_map.update(calculated_types)
            table = next(
                (item for item in next_project.get("model", {}).get("tables", [])
                 if item.get("id") == source_id or item.get("source_id") == source_id),
                None,
            )
            if table is not None:
                table["column_types"] = type_map
            else:
                next_project.setdefault("model", {}).setdefault("tables", []).append({
                    "id": source_id,
                    "source_id": source_id,
                    "name": str(target.get("name", "Table")),
                    "column_types": type_map,
                })
            next_project = validate_project(next_project)
            dependent_candidates, dependent_types = self._rebuild_query_dependents(
                next_project, {source_id: calculated_candidate}
            )
            for dependent_id, dependent_type_map in dependent_types.items():
                dependent_table = next(
                    (item for item in next_project["model"]["tables"]
                     if item.get("id") == dependent_id
                     or item.get("source_id") == dependent_id),
                    None,
                )
                if dependent_table is not None:
                    dependent_table["column_types"] = dependent_type_map
            next_project = validate_project(next_project)
        except (StopIteration, OSError, ProjectFileError, QueryError, TypeError, ValueError) as exc:
            self._set_status(f"Could not apply transformations: {exc}")
            return False

        self._project = next_project
        self._loaded_candidates.update(dependent_candidates)
        for updated_id in dependent_candidates:
            self._source_load_errors.pop(updated_id, None)
        if source_id == self._active_source_id:
            self._headers = list(calculated_candidate.headers)
            self._rows = [dict(row) for row in calculated_candidate.rows]
            self._table_model.replace_data(self._headers, self._rows)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Applied {len(validated_steps)} transformation step(s)")
        return True

    def _source_id_for_path(
        self,
        path: Path,
        *,
        kind: str | None = None,
        parser_options: dict[str, Any] | None = None,
    ) -> str | None:
        target = Path(path).expanduser().resolve()
        for source in self._project.get("data_sources", []):
            if source.get("kind") == "inline" or not source.get("path"):
                continue
            if kind is not None and source.get("kind") != kind:
                continue
            if kind == "sqlite" and parser_options is not None:
                existing_options = source.get("parser_options", {})
                if existing_options.get("table_name") != parser_options.get("table_name"):
                    continue
            try:
                if self._resolved_source_path(source) == target:
                    return str(source["id"])
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
        return None

    def _unique_table_name(self, desired_name: str) -> str:
        base = desired_name.strip() or "Table"
        used = {
            str(table.get("name", "")).casefold()
            for table in self._project.get("model", {}).get("tables", [])
        }
        if base.casefold() not in used:
            return base
        suffix = 2
        while f"{base} ({suffix})".casefold() in used:
            suffix += 1
        return f"{base} ({suffix})"

    def refresh_source(self) -> None:
        if self.activeSourceExcludedFromRefresh:
            source = next(
                (item for item in self._project.get("data_sources", [])
                 if item.get("id") == self._active_source_id),
                None,
            )
            self._set_status(
                f"{source.get('name', 'This query')} is excluded from report refresh."
                if source else "The active query is excluded from report refresh."
            )
            return
        if not self.canRefreshSource or self._active_source_id is None:
            self._set_status("The active source cannot be refreshed")
            return

        self._refresh_sources([self._active_source_id], refresh_all=False)

    def refresh_all_sources(self) -> None:
        if not self.canRefreshAllSources:
            self._set_status("There are no linked sources available to refresh.")
            return
        roots = [
            str(source["id"])
            for source in self._project.get("data_sources", [])
            if self._source_is_refresh_root(source)
        ]
        self._refresh_sources(roots, refresh_all=True)

    def _refresh_sources(self, root_ids: list[str], *, refresh_all: bool) -> None:
        sources = self._project.get("data_sources", [])
        sources_by_id = {str(source["id"]): source for source in sources}
        valid_roots = [source_id for source_id in root_ids if source_id in sources_by_id]
        if not valid_roots:
            self._set_status("There are no linked sources available to refresh.")
            return
        active_source = sources_by_id.get(self._active_source_id or "")
        if not refresh_all and active_source is None:
            self._set_status("The active source record is unavailable.")
            return
        affected_ids: set[str] = set()

        def include_dependencies(source_id: str) -> None:
            if source_id in affected_ids:
                return
            source = sources_by_id[source_id]
            affected_ids.add(source_id)
            if (
                source.get("kind") == "query"
                and self._source_refresh_included(source)
            ):
                for dependency in source["query_definition"]["source_ids"]:
                    include_dependencies(dependency)

        refreshing_source_id: str | None = None
        try:
            for root_id in valid_roots:
                include_dependencies(root_id)
            changed = True
            while changed:
                changed = False
                for source in sources:
                    if source.get("kind") != "query" or source["id"] in affected_ids:
                        continue
                    if any(
                        dependency in affected_ids
                        for dependency in source["query_definition"]["source_ids"]
                    ):
                        include_dependencies(str(source["id"]))
                        changed = True

            ordered = [
                source for source in self._source_dependency_order(sources)
                if str(source["id"]) in affected_ids
            ]
            refreshed: dict[str, ImportCandidate] = {}
            raw_candidates: dict[str, ImportCandidate] = {}
            query_candidates: dict[str, ImportCandidate] = {}
            calculated_type_maps: dict[str, dict[str, str]] = {}
            for source in ordered:
                source_id = str(source["id"])
                refreshing_source_id = source_id
                kind = source.get("kind")
                if kind == "query":
                    if not self._source_refresh_included(source):
                        previous = self._loaded_candidates.get(source_id)
                        if previous is None:
                            raise QueryError(
                                f"Cannot refresh dependent query {source.get('name', source_id)!r}: "
                                "it is excluded from report refresh and has no cached result. "
                                "Include it in report refresh and try again."
                            )
                        refreshed[source_id] = previous
                        continue
                    raw = self._query_candidate(
                        source, refreshed, project=self._project
                    )
                elif kind == "inline":
                    raw = self._raw_candidate_for_source(source)
                elif kind == "sql_server":
                    raw = self._sql_server_candidate_for_source(source)
                elif kind == "odata":
                    raw = self._odata_candidate_for_source(source)
                elif kind == "web":
                    raw = self._web_candidate_for_source(source)
                elif kind == "folder":
                    raw = parse_folder(
                        self._resolved_source_path(source),
                        options=source.get("parser_options", {}),
                    )
                else:
                    raw = parse_file(
                        self._resolved_source_path(source),
                        options=source.get("parser_options", {}),
                        expected_kind=kind,
                    )
                raw_candidates[source_id] = raw
                query_candidate = apply_transformations(
                    raw, source.get("transform_steps", [])
                )
                base_types = column_types_after_steps(
                    raw.headers,
                    source.get("transform_steps", []),
                    output_headers=query_candidate.headers,
                )
                query_candidates[source_id] = query_candidate
                refreshed[source_id], calculated_type_maps[source_id] = (
                    self._apply_calculated_columns(
                        source_id, query_candidate, column_types=base_types
                    )
                )

            next_project = deepcopy(self._project)
            metadata_changed = False
            for source_id, raw in raw_candidates.items():
                source = sources_by_id[source_id]
                type_map = column_types_after_steps(
                    raw.headers,
                    source.get("transform_steps", []),
                    output_headers=query_candidates[source_id].headers,
                )
                type_map.update(calculated_type_maps.get(source_id, {}))
                table = next(
                    (item for item in next_project.get("model", {}).get("tables", [])
                     if item.get("id") == source_id or item.get("source_id") == source_id),
                    None,
                )
                if table is not None and table.get("column_types", {}) != type_map:
                    table["column_types"] = type_map
                    metadata_changed = True
            next_project = validate_project(next_project)
        except (KeyError, OSError, ProjectFileError, TypeError, ValueError) as exc:
            failed_source = sources_by_id.get(refreshing_source_id or "", active_source or {})
            failed_name = str(failed_source.get("name", "the source"))
            failed_id = refreshing_source_id or self._active_source_id
            if failed_id:
                self._source_load_errors[failed_id] = f"Could not refresh {failed_name}: {exc}"
            self._source_warning = self._compose_source_warning()
            self.stateChanged.emit()
            title = "Could not refresh all sources" if refresh_all else "Could not refresh source"
            detail = f"Could not refresh {failed_name}:\n\n{exc}" if refresh_all else str(exc)
            QMessageBox.critical(None, title, detail)
            return

        self._project = next_project
        self._loaded_candidates.update(refreshed)
        if metadata_changed:
            self._dirty = True
        for source_id in affected_ids:
            self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        active_candidate = (
            refreshed.get(self._active_source_id or "")
            or self._loaded_candidates.get(self._active_source_id or "")
        )
        if self._active_source_id and active_candidate is not None:
            self._install_source(
                self._active_source_path,
                self._active_source_id,
                active_candidate,
            )
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        if refresh_all:
            notice = next(
                (candidate.notices[0] for candidate in refreshed.values() if candidate.notices),
                "",
            )
            suffix = f" · {notice}" if notice else ""
            self._set_status(
                f"Refreshed all supported linked sources and dependent queries{suffix}"
            )
        else:
            refreshed_active = refreshed.get(self._active_source_id or "")
            notices = refreshed_active.notices if refreshed_active else []
            suffix = f" · {notices[0]}" if notices else ""
            self._set_status(
                f"Refreshed {active_source.get('name', 'the active source')}{suffix}"
            )


    @Slot()
    def add_page(self) -> None:
        pages = self._project["report"]["pages"]
        page = {
            "id": str(uuid4()),
            "name": f"Page {len(pages) + 1}",
            "visuals": [],
            "filters": [],
            "visual_filters": [],
            "hidden": False,
        }
        pages.append(page)
        self._active_page_id = page["id"]
        self._project["report"]["active_page_id"] = page["id"]
        self._selected_visual = ""
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Added {page['name']}")

    @Slot(str, str)
    def rename_page(self, page_id: str, new_name: str) -> None:
        if not new_name.strip():
            return
        pages = self._project["report"]["pages"]
        for page in pages:
            if page["id"] == page_id:
                page["name"] = new_name.strip()
                self._dirty = True
                self.stateChanged.emit()
                self._set_status(f"Renamed page to {new_name}")
                return

    @Slot(str)
    def delete_page(self, page_id: str) -> None:
        pages = self._project["report"]["pages"]
        if len(pages) <= 1:
            return # Must preserve at least one page
        
        index_to_remove = -1
        for i, page in enumerate(pages):
            if page["id"] == page_id:
                index_to_remove = i
                break
        
        if index_to_remove != -1:
            deleted_name = pages[index_to_remove]["name"]
            del pages[index_to_remove]
            if self._active_page_id == page_id:
                new_idx = max(0, index_to_remove - 1)
                self._active_page_id = pages[new_idx]["id"]
                self._project["report"]["active_page_id"] = self._active_page_id
                self._selected_visual = ""
            self._dirty = True
            self._refresh_report()
            self.stateChanged.emit()
            self._set_status(f"Deleted {deleted_name}")

    @Slot(str)

    @Slot(str, int, int)
    def move_visual(self, visual_id: str, x: int, y: int) -> None:
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("id") == visual_id:
                visual["x"] = max(0, x)
                visual["y"] = max(0, y)
                self._dirty = True
                self.stateChanged.emit()
                return


    @Slot(str, str)
    def add_field_to_well(self, well_name: str, field_name: str) -> None:
        if not self._selected_visual: return
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == self._selected_visual:
                fields = visual.setdefault("fields", {})
                well_fields = fields.setdefault(well_name, [])
                if field_name not in well_fields:
                    well_fields.append(field_name)
                    self._dirty = True
                    self._refresh_report()
                    self.stateChanged.emit()
                break

    @Slot(str, str)
    def remove_field_from_well(self, well_name: str, field_name: str) -> None:
        if not self._selected_visual: return
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == self._selected_visual:
                fields = visual.setdefault("fields", {})
                well_fields = fields.setdefault(well_name, [])
                if field_name in well_fields:
                    well_fields.remove(field_name)
                    self._dirty = True
                    self._refresh_report()
                    self.stateChanged.emit()
                break

    @Slot(str, str)
    def set_visual_type(self, title: str, v_type: str) -> None:
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == title:
                visual["type"] = v_type
                self._dirty = True
                self.stateChanged.emit()
                return

    @Slot(str, "QVariant")
    def set_visual_property(self, property_key: str, value: object) -> None:
        if not self._selected_visual: return
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == self._selected_visual:
                if property_key == "title" and str(value) != str(visual["title"]):
                    # Keep selected_visual synced if title changes
                    self._selected_visual = str(value)
                visual[property_key] = value
                self._dirty = True
                self.stateChanged.emit()
                break

    @Slot(str, int, int)
    def resize_visual(self, visual_id: str, width: int, height: int) -> None:
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("id") == visual_id:
                visual["width"] = max(10, width)
                visual["height"] = max(10, height)
                self._dirty = True
                self.stateChanged.emit()
                return

    @Slot(str)
    def remove_visual(self, visual_id: str) -> None:
        page = self._project["report"]["pages"][self.activePageIndex]
        visuals = page.get("visuals", [])
        index_to_remove = -1
        for i, visual in enumerate(visuals):
            if isinstance(visual, dict) and visual.get("id") == visual_id:
                index_to_remove = i
                break
        if index_to_remove != -1:
            name = visuals[index_to_remove].get("title", "")
            del visuals[index_to_remove]
            if self._selected_visual == name:
                self._selected_visual = ""
            self._dirty = True
            self.stateChanged.emit()
            self._set_status(f"Removed visual")

    @Slot(str, str, int, int, int, int)
    def add_visual(self, v_type: str, title: str, x: int, y: int, width: int, height: int) -> str:
        from uuid import uuid4
        page = self._project["report"]["pages"][self.activePageIndex]
        visuals = page.setdefault("visuals", [])
        new_id = str(uuid4())
        visuals.append({
            "id": new_id,
            "type": v_type,
            "title": title,
            "x": x,
            "y": y,
            "width": width,
            "height": height
        })
        self._dirty = True
        self._selected_visual = title
        self.stateChanged.emit()
        self._set_status(f"Added visual {title}")
        return new_id

    def duplicate_page(self, page_id: str) -> None:
        pages = self._project["report"]["pages"]
        source_page = next((p for p in pages if p["id"] == page_id), None)
        if not source_page:
            return
            
        import copy
        new_page = copy.deepcopy(source_page)
        new_page["id"] = str(uuid4())
        new_page["name"] = source_page["name"] + " (Copy)"
        
        # Insert adjacent to the source page
        original_idx = pages.index(source_page)
        pages.insert(original_idx + 1, new_page)
        
        self._active_page_id = new_page["id"]
        self._project["report"]["active_page_id"] = new_page["id"]
        self._selected_visual = ""
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Duplicated {source_page['name']}")

    @Slot(str, bool)
    def hide_page(self, page_id: str, hidden: bool) -> None:
        pages = self._project["report"]["pages"]
        for page in pages:
            if page["id"] == page_id:
                page["hidden"] = hidden
                self._dirty = True
                self.stateChanged.emit()
                status_str = "Hid" if hidden else "Unhid"
                self._set_status(f"{status_str} {page['name']}")
                return

    @Slot(str, int)
    def reorder_page(self, page_id: str, new_index: int) -> None:
        pages = self._project["report"]["pages"]
        current_index = -1
        for i, page in enumerate(pages):
            if page["id"] == page_id:
                current_index = i
                break
                
        if current_index != -1 and 0 <= new_index < len(pages) and current_index != new_index:
            page = pages.pop(current_index)
            pages.insert(new_index, page)
            self._dirty = True
            self.stateChanged.emit()
            self._set_status(f"Reordered {page['name']}")


    def add_chart(self, visual_name: str) -> None:
        if visual_name not in CHART_VISUALS:
            return
        page = self._project["report"]["pages"][self.activePageIndex]
        visuals = page.setdefault("visuals", [])
        if not any(isinstance(v, dict) and v.get("title") == visual_name for v in visuals):
            from uuid import uuid4
            is_monthly = "Monthly" in visual_name
            visuals.append({
                "id": str(uuid4()),
                "type": "column" if is_monthly else "bar",
                "title": visual_name,
                "x": 14 if is_monthly else 358,
                "y": 108,
                "width": 330,
                "height": 248
            })
            self._dirty = True
        self._selected_visual = visual_name
        self.stateChanged.emit()
        self._set_status(f"Added {visual_name}")

    def clear_filters(self) -> None:
        page = self._active_page()
        report_filters = self._project.get("report", {}).get("filters", [])
        page_filters = page.get("filters", []) if page else []
        visual_filters = page.get("visual_filters", []) if page else []
        if self._current_region is None and not report_filters and not page_filters and not visual_filters:
            return
        self._current_region = None
        self._project.setdefault("report", {})["filters"] = []
        if page is not None:
            page["filters"] = []
            page["visual_filters"] = []
        if report_filters or page_filters or visual_filters:
            self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status("Report and current-page filters cleared")

    def show_about(self) -> None:
        QMessageBox.about(
            None,
            "About Analytics Studio",
            "Analytics Studio\nA native desktop analytics authoring workspace.",
        )

    def show_shortcuts(self) -> None:
        QMessageBox.information(
            None,
            "Keyboard shortcuts",
            "New Project: ⌘N / Ctrl+N\nOpen Project: ⌘O / Ctrl+O\n"
            "Save Project: ⌘S / Ctrl+S\nSave As: ⇧⌘S / Ctrl+Shift+S",
        )

    def show_project_format(self) -> None:
        QMessageBox.information(
            None,
            "Project format",
            "Analytics Studio projects use the versioned .npa JSON format (currently v55). "
            "Imported files stay linked as external sources; SQL Server passwords use a local Keychain reference, OData Feed sources store an anonymous HTTPS service root, and Web sources store their anonymous HTTPS URL; "
            "entered tables, append and merge query definitions, "
            "transform steps, and local measure formulas are saved in the project. A .bak recovery copy is kept on later saves.",
        )

    def quit_application(self) -> None:
        if self._confirm_replace_project():
            QApplication.quit()

    def save_current_project(self) -> bool:
        if self._project_path is None:
            return self.save_project_as()
        return self._save_to(self._project_path)

    def save_project_as(self) -> bool:
        suggested = f"{self.projectName}.npa"
        path, _ = QFileDialog.getSaveFileName(
            None, "Save Analytics Studio project", suggested, "Analytics Studio project (*.npa)"
        )
        if not path:
            return False
        if not path.lower().endswith(".npa"):
            path += ".npa"
        return self._save_to(Path(path))

    def export_data_dialog(self) -> bool:
        if not self.sourceLoaded or not self._headers:
            self._set_status("Load a table before exporting data.")
            return False
        path, _ = QFileDialog.getSaveFileName(
            None,
            "Export active table as CSV",
            f"{self.sourceName or 'table'}.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return False
        target = Path(path)
        if target.suffix.casefold() != ".csv":
            target = target.with_suffix(".csv")
        return self.export_data_path(target)

    def export_data_path(self, path: Path) -> bool:
        """Export the current transformed table as UTF-8 CSV, without changing it."""
        if not self.sourceLoaded or not self._headers:
            self._set_status("Load a table before exporting data.")
            return False
        path = Path(path).expanduser().resolve()
        temp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow(self._headers)
                for row in self._rows:
                    writer.writerow([
                        "" if row.get(header) is None else str(row.get(header, ""))
                        for header in self._headers
                    ])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except (OSError, csv.Error) as exc:
            self._set_status(f"Could not export data: {exc}")
            return False
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self._set_status(f"Exported {len(self._rows):,} rows to {path.name}")
        return True

    def _save_to(self, path: Path) -> bool:
        path = Path(path).expanduser().resolve()
        candidate = self._document_for_save(path)
        try:
            saved = save_project(
                path,
                candidate,
                recovered_from_backup=(
                    self._recovered_from_backup and path == self._project_path
                ),
            )
        except (OSError, ProjectFileError) as exc:
            QMessageBox.critical(None, "Could not save project", str(exc))
            return False

        self._project = saved
        self._project_path = path
        self._recovered_from_backup = False
        self._dirty = False
        self._active_page_id = saved["report"]["active_page_id"]
        self.stateChanged.emit()
        self._set_status(f"Saved {path.name}")
        return True

    def _document_for_save(self, path: Path) -> dict[str, Any]:
        document = deepcopy(self._project)
        document["active_source_id"] = self._active_source_id
        document["name"] = path.stem if path != self._project_path else self.projectName
        document["active_view"] = self._current_view
        document["report"]["active_page_id"] = self._active_page_id
        document["report"]["chart_types"] = {
            "monthly": self.monthlyChartType,
            "region": self.regionChartType,
        }

        active_id = self._active_source_id
        active_path = self._active_source_path
        if active_id is not None and self._active_source_kind == "inline":
            for source in document.get("data_sources", []):
                if source.get("id") != active_id and source.get("kind") not in PATHLESS_SOURCE_KINDS:
                    source["path"] = self._source_path_for_save(source["path"], path)
            existing_table = next(
                (table for table in document["model"].get("tables", [])
                 if table.get("id") == active_id or table.get("source_id") == active_id),
                None,
            )
            table_record = {
                "id": active_id,
                "name": str(existing_table.get("name")) if existing_table else (self.sourceName or "Entered data"),
                "source_id": active_id,
            }
            tables = document["model"].setdefault("tables", [])
            for index, table in enumerate(tables):
                if table.get("id") == active_id or table.get("source_id") == active_id:
                    tables[index] = {**table, **table_record}
                    break
            else:
                tables.append(table_record)
        elif active_id is not None and active_path is not None:
            source_record = {
                "id": active_id,
                "name": active_path.name,
                "kind": self._active_source_kind or self._source_kind_for_path(active_path),
                "path": source_path_for_save(active_path, path),
                "parser_options": dict(self._active_parser_options),
            }
            source_replaced = False
            for index, source in enumerate(document.get("data_sources", [])):
                if source.get("id") == active_id:
                    document["data_sources"][index] = {**source, **source_record}
                    source_replaced = True
                elif source.get("kind") not in PATHLESS_SOURCE_KINDS:
                    source["path"] = self._source_path_for_save(source["path"], path)
            if not source_replaced:
                document.setdefault("data_sources", []).append(source_record)

            if self.sourceLoaded:
                existing_table = next(
                    (table for table in document["model"].get("tables", [])
                     if table.get("id") == active_id or table.get("source_id") == active_id),
                    None,
                )
                table_record = {
                    "id": active_id,
                    "name": str(existing_table.get("name")) if existing_table else active_path.stem,
                    "source_id": active_id,
                }
                tables = document["model"].setdefault("tables", [])
                for index, table in enumerate(tables):
                    if table.get("id") == active_id or table.get("source_id") == active_id:
                        tables[index] = {**table, **table_record}
                        break
                else:
                    tables.append(table_record)
        else:
            # Paths were resolved on open so Save As can preserve links from the new location.
            for source in document.get("data_sources", []):
                if source.get("kind") not in PATHLESS_SOURCE_KINDS:
                    source["path"] = self._source_path_for_save(source["path"], path)
        return document

    def _source_path_for_save(self, stored_path: str, destination: Path) -> str:
        source_path = Path(stored_path).expanduser()
        if not source_path.is_absolute() and self._project_path is not None:
            source_path = resolve_source_path(stored_path, self._project_path)
        if source_path.is_absolute():
            return source_path_for_save(source_path, destination)
        return stored_path

    def _confirm_replace_project(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            None,
            "Unsaved project changes",
            "Save changes to this project before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current_project()
        return answer == QMessageBox.StandardButton.Discard

    def _replace_with_new_project(self) -> None:
        self._project = new_project()
        self._project_path = None
        self._recovered_from_backup = False
        self._dirty = False
        self._current_view = "Report"
        self._active_page_id = self._project["report"]["active_page_id"]
        self._active_source_id = None
        self._active_source_path = None
        self._active_source_kind = None
        self._active_parser_options = {}
        self._loaded_candidates = {}
        self._source_load_errors = {}
        self._selected_visual = ""
        self._field_query = ""
        self._current_region = None
        self._clear_source(clear_selection=True)
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status("New project")

    @staticmethod
    def _source_kind_for_path(path: Path) -> str:
        return kind_for_path(path)

    def _install_source(
        self,
        path: Path | None,
        source_id: str,
        parsed: ImportCandidate,
    ) -> None:
        self._loaded_candidates[source_id] = parsed
        self._source_path = path
        self._source_id = source_id
        self._active_source_id = source_id
        self._active_source_path = path
        self._active_source_kind = parsed.kind
        self._active_parser_options = dict(parsed.options)
        self._headers = list(parsed.headers)
        self._rows = list(parsed.rows)
        self._table_model.replace_data(parsed.headers, parsed.rows)
        if self._current_region not in self.regions:
            self._current_region = None

    def _clear_source(self, *, clear_selection: bool = True) -> None:
        self._source_path = None
        self._source_id = None
        self._headers = []
        self._rows = []
        self._current_region = None
        self._source_warning = ""
        self._table_model.clear()
        if clear_selection:
            self._active_source_id = None
            self._active_source_path = None
            self._active_source_kind = None
            self._active_parser_options = {}

    def _page_relative_filter_kinds(self) -> tuple[bool, bool]:
        page = self._active_page()
        report_filters = [
            report_filter
            for report_filter in self._project.get("report", {}).get("filters", [])
        ]
        if page is not None:
            report_filters.extend(
                report_filter
                for key in ("filters", "visual_filters")
                for report_filter in page.get(key, [])
            )
        return (
            any(_report_filter_has_relative_date(item) for item in report_filters),
            any(_report_filter_has_relative_time(item) for item in report_filters),
        )

    def _schedule_relative_filter_refresh(self, now: datetime) -> None:
        has_relative_date, has_relative_time = self._page_relative_filter_kinds()
        if not has_relative_date and not has_relative_time:
            self._relative_filter_timer.stop()
            return
        next_boundaries = []
        if has_relative_date:
            next_boundaries.append(datetime.combine(
                now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
            ))
        if has_relative_time:
            next_boundaries.append(
                now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            )
        next_boundary = min(next_boundaries)
        milliseconds = int((next_boundary - now).total_seconds() * 1000) + 1
        self._relative_filter_timer.start(max(1, milliseconds))

    def _on_relative_filter_boundary(self) -> None:
        self._refresh_report()
        self.stateChanged.emit()

    def _apply_visual_top_n_rows(
        self,
        visual_name: str,
        source_rows: list[dict[str, Any]],
        active_table_id: str,
    ) -> list[dict[str, Any]]:
        if visual_name != "Region revenue":
            return source_rows
        page = self._active_page()
        if page is None:
            return source_rows
        table = next(
            (item for item in self._table_catalog if item.get("id") == active_table_id),
            None,
        )
        candidate = self._loaded_candidates.get(str(table.get("sourceId", ""))) if table else None
        if candidate is None:
            return source_rows
        region_column = _report_field(candidate.headers, "region")
        if region_column is None:
            return source_rows

        for report_filter in page.get("visual_filters", []):
            if report_filter.get("visual_name") != visual_name:
                continue
            clause = next((
                item for item in report_filter.get("clauses", [])
                if item.get("operator") == _REPORT_FILTER_TOP_N
            ), None)
            if clause is None:
                continue
            order_by = clause.get("order_by", {})
            target_column = str(report_filter.get("column", ""))
            order_table_id = str(order_by.get("table_id", ""))
            order_column = str(order_by.get("column", ""))
            if (
                str(report_filter.get("table_id", "")) != active_table_id
                or target_column != region_column
                or order_table_id != active_table_id
                or order_column not in candidate.headers
                or order_column == target_column
            ):
                continue

            totals: defaultdict[str, Decimal] = defaultdict(Decimal)
            for row in source_rows:
                label = str(row.get(target_column, "") or "Unknown").strip() or "Unknown"
                amount = _report_number(row.get(order_column, ""))
                if amount is not None:
                    totals[label] += amount
            if clause.get("direction") == "bottom":
                ranked = sorted(totals.items(), key=lambda item: (item[1], item[0].casefold(), item[0]))
            else:
                ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold(), item[0]))
            selected = {label for label, _ in ranked[:int(clause.get("count", 0))]}
            return [
                row for row in source_rows
                if (str(row.get(target_column, "") or "Unknown").strip() or "Unknown") in selected
            ]
        return source_rows

    def _refresh_report(self) -> None:
        now = datetime.now(timezone.utc)
        self._relative_filter_anchor_date = now.date()
        self._relative_filter_anchor_time = now
        self._schedule_relative_filter_refresh(now)
        defaults = {name: "—" for name in ("Revenue", "Cost", "Margin", "Units", "Orders")}
        self._measure_values = {}
        self._measure_errors = {}
        self._visual_kpis = {}
        self._monthly_visual_series = {}
        self._region_visual_series = {}
        self._clipboard_visual_config = None
        self._clipboard_format_config = None
        self._format_painter_active = False
        self._region_column = _report_field(self._headers, "region") if self.sourceLoaded else None
        if not self.sourceLoaded:
            self._kpis = defaults
            self._monthly_series = []
            self._region_series = []
            self._filter_context_error = ""
            self._monthly_chart_message = "No date and numeric sales field found in this source."
            self._region_chart_message = "No region and numeric sales field found in this source."
            return

        if self._current_region is not None and self._current_region not in self.regions:
            self._current_region = None
        filtered_rows_by_table, measure_table_context, filter_table_ids = (
            self._report_filter_context()
        )
        active_table_id = self._active_model_table_id()
        rows = filtered_rows_by_table.get(active_table_id, list(self._rows))
        revenue_column = _report_field(self._headers, "revenue")
        cost_column = _report_field(self._headers, "cost")
        margin_column = _report_field(self._headers, "margin")
        units_column = _report_field(self._headers, "units")
        date_column = _report_field(self._headers, "date")
        region_column = self._region_column

        def standard_kpis(source_rows: list[dict[str, Any]]) -> dict[str, str]:
            def total(column: str | None) -> Decimal | None:
                if column is None:
                    return None
                values = [_report_number(row.get(column, "")) for row in source_rows]
                numbers = [value for value in values if value is not None]
                return sum(numbers, Decimal(0)) if numbers else None

            revenue_total = total(revenue_column)
            cost_total = total(cost_column)
            margin_total = total(margin_column)
            if margin_total is None and revenue_total is not None and cost_total is not None:
                margin_total = revenue_total - cost_total
            units_total = total(units_column)
            return {
                "Revenue": _format_report_number(revenue_total) if revenue_total is not None else "—",
                "Cost": _format_report_number(cost_total) if cost_total is not None else "—",
                "Margin": _format_report_number(margin_total) if margin_total is not None else "—",
                "Units": _format_report_number(units_total) if units_total is not None else "—",
                "Orders": f"{len(source_rows):,}",
            }

        def chart_series(
            source_rows: list[dict[str, Any]],
        ) -> tuple[list[dict[str, str | float]], list[dict[str, str | float]]]:
            monthly: defaultdict[str, Decimal] = defaultdict(Decimal)
            regions: defaultdict[str, Decimal] = defaultdict(Decimal)
            if revenue_column:
                for row in source_rows:
                    amount = _report_number(row.get(revenue_column, ""))
                    if amount is None:
                        continue
                    month = _report_month(row.get(date_column, "")) if date_column else None
                    if month:
                        monthly[month] += amount
                    if region_column:
                        region = str(row.get(region_column, "") or "Unknown").strip() or "Unknown"
                        regions[region] += amount
            return (
                [{"label": key, "value": float(value)} for key, value in sorted(monthly.items())],
                [{"label": key, "value": float(value)} for key, value in sorted(regions.items())],
            )

        self._kpis = standard_kpis(rows)
        self._monthly_series, self._region_series = chart_series(rows)
        self._monthly_chart_message = (
            "No sales or revenue column found in this source."
            if revenue_column is None else
            "No date column found in this source."
            if date_column is None else
            "No usable dates and numeric sales values found in this source."
        )
        self._region_chart_message = (
            "No sales or revenue column found in this source."
            if revenue_column is None else
            "No region or geographic column found in this source."
            if region_column is None else
            "No numeric sales values found for the region chart."
        )

        measures = self._project.get("model", {}).get("measures", [])
        relationships = self._project.get("model", {}).get("relationships", [])

        def evaluate_one_measure(
            name: str,
            measure_rows: list[dict[str, Any]],
            table_context: list[dict[str, Any]],
            filter_ids: set[str],
        ) -> Decimal:
            return evaluate_measures(
                measures,
                measure_rows,
                self._headers,
                self._active_model_table_name(),
                measure_names=[name],
                table_context=table_context,
                relationships=relationships,
                filter_table_ids=filter_ids,
                active_table_id=active_table_id or None,
            )[name]

        for measure in measures:
            name = str(measure["name"])
            try:
                value = evaluate_one_measure(
                    name, rows, measure_table_context, filter_table_ids
                )
            except MeasureError as exc:
                self._measure_errors[name] = str(exc)
            else:
                formatted = _format_report_number(value)
                self._measure_values[name] = formatted
                self._kpis[name] = formatted

        filter_errors = [self._filter_context_error] if self._filter_context_error else []
        page = self._active_page()
        visuals_with_filters = {
            str(item.get("visual_name", ""))
            for item in (page.get("visual_filters", []) if page else [])
        }
        measure_names = {str(measure["name"]) for measure in measures}
        for visual_name in self.activePageVisuals:
            visual_rows = rows
            visual_context = measure_table_context
            visual_filter_ids = filter_table_ids
            if visual_name in visuals_with_filters:
                (
                    visual_rows_by_table,
                    visual_context,
                    visual_filter_ids,
                ) = self._report_filter_context(visual_name)
                visual_rows = visual_rows_by_table.get(active_table_id, list(self._rows))
                if self._filter_context_error:
                    filter_errors.append(self._filter_context_error)

            if visual_name == "Monthly revenue":
                self._monthly_visual_series[visual_name] = chart_series(visual_rows)[0]
            elif visual_name == "Region revenue":
                visual_rows = self._apply_visual_top_n_rows(
                    visual_name, visual_rows, active_table_id
                )
                self._region_visual_series[visual_name] = chart_series(visual_rows)[1]
            elif visual_name.endswith(" KPI"):
                kpi_name = visual_name[:-4]
                if kpi_name in measure_names:
                    try:
                        visual_value = evaluate_one_measure(
                            kpi_name, visual_rows, visual_context, visual_filter_ids
                        )
                    except MeasureError:
                        self._visual_kpis[visual_name] = "—"
                    else:
                        self._visual_kpis[visual_name] = _format_report_number(visual_value)
                else:
                    self._visual_kpis[visual_name] = standard_kpis(visual_rows).get(kpi_name, "—")

        self._filter_context_error = "; ".join(dict.fromkeys(filter_errors))

    def _generate_dynamic_visual_series(self, visual_name: str) -> list[dict[str, str | float]]:
        page = self._active_page()
        if not page:
            return []
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == visual_name), None)
        if not visual:
            return []
            
        fields = visual.get("fields", {})
        x_axis = fields.get("X-axis", [])
        y_axis = fields.get("Y-axis", [])
        
        # If no fields are mapped in dynamic wells, fall back to legacy series for initial views
        if not x_axis and not y_axis:
            if visual_name == "Monthly revenue":
                return self._monthly_visual_series.get(visual_name, self._monthly_series)
            elif visual_name == "Region revenue":
                return self._region_visual_series.get(visual_name, self._region_series)
            return []
            
        x_col = x_axis[0] if x_axis else None
        y_col = y_axis[0] if y_axis else None
        
        visual_rows = list(self._rows)
        active_table_id = self._active_source_id
        visuals_with_filters = {str(item.get("visual_name", "")) for item in page.get("visual_filters", [])}
        if visual_name in visuals_with_filters:
            (visual_rows_by_table, _, _) = self._report_filter_context(visual_name)
            visual_rows = visual_rows_by_table.get(active_table_id, list(self._rows))

        from collections import defaultdict
        from decimal import Decimal
        aggregated: defaultdict[str, Decimal] = defaultdict(Decimal)
        for row in visual_rows:
            if y_col:
                val = row.get(y_col, "")
                if val:
                    # Strip currency symbols and commas if it's a string, then parse
                    val_str = str(val).replace("$", "").replace(",", "").strip()
                    try:
                        amount = Decimal(val_str)
                    except Exception:
                        continue
                else:
                    continue
            else:
                amount = Decimal(1)
            
            key = str(row.get(x_col, "")) if x_col else "(Blank)"
            if key:
                aggregated[key] += amount

        if visual.get("type", "bar") == "column":
            series = [{"label": key, "value": float(value)} for key, value in sorted(aggregated.items())]
        else:
            series = [{"label": key, "value": float(value)} for key, value in sorted(aggregated.items(), key=lambda x: x[1], reverse=True)]

        return series

    def _refresh_model_view(self) -> None:
        model = self._project.get("model", {})
        sources = self._project.get("data_sources", [])
        sources_by_id = {str(source.get("id")): source for source in sources}
        catalog: list[dict[str, Any]] = []
        catalog_source_ids: set[str] = set()
        for table in model.get("tables", []):
            source_id = str(table.get("source_id") or table.get("id") or "")
            source = sources_by_id.get(source_id)
            parsed = self._loaded_candidates.get(source_id)
            name = str(table.get("name", "Unnamed table"))
            query_group = str(source.get("query_group", "")) if source else ""
            load_enabled = self._source_load_enabled(source) if source else True
            query_definition = source.get("query_definition", {}) if source else {}
            query_operation = str(query_definition.get("operation", ""))
            query_expression = (
                calendar_expression(query_definition)
                if query_operation in {"calendar", "calendar_auto"}
                else str(query_definition.get("expression", ""))
            )
            catalog.append({
                "id": str(table.get("id") or source_id),
                "sourceId": source_id,
                "name": name,
                "displayName": f"{query_group} / {name}" if query_group else name,
                "queryGroup": query_group,
                "kind": str(source.get("kind", "")) if source else "",
                "queryOperation": query_operation,
                "queryExpression": query_expression,
                "querySourceIds": list(query_definition.get("source_ids", [])),
                "loaded": parsed is not None and load_enabled,
                "evaluated": parsed is not None,
                "loadEnabled": load_enabled,
                "includeInReportRefresh": (
                    self._source_refresh_included(source) if source else True
                ),
                "active": source_id == self._active_source_id,
                "rowCount": len(parsed.rows) if parsed else 0,
                "columnCount": len(parsed.headers) if parsed else 0,
                "headers": list(parsed.headers) if parsed else [],
                "columnTypes": dict(table.get("column_types", {})),
                "dateColumn": str(table.get("date_column") or ""),
                "calculatedColumns": [
                    dict(item) for item in table.get("calculated_columns", [])
                ],
            })
            if source_id:
                catalog_source_ids.add(source_id)

        for source in sources:
            source_id = str(source.get("id", ""))
            if not source_id or source_id in catalog_source_ids:
                continue
            parsed = self._loaded_candidates.get(source_id)
            name = str(source.get("name", "Unnamed table"))
            query_group = str(source.get("query_group", ""))
            load_enabled = self._source_load_enabled(source)
            query_definition = source.get("query_definition", {})
            query_operation = str(query_definition.get("operation", ""))
            query_expression = (
                calendar_expression(query_definition)
                if query_operation in {"calendar", "calendar_auto"}
                else str(query_definition.get("expression", ""))
            )
            catalog.append({
                "id": source_id,
                "sourceId": source_id,
                "name": name,
                "displayName": f"{query_group} / {name}" if query_group else name,
                "queryGroup": query_group,
                "kind": str(source.get("kind", "")),
                "queryOperation": query_operation,
                "queryExpression": query_expression,
                "querySourceIds": list(query_definition.get("source_ids", [])),
                "loaded": parsed is not None and load_enabled,
                "evaluated": parsed is not None,
                "loadEnabled": load_enabled,
                "includeInReportRefresh": self._source_refresh_included(source),
                "active": source_id == self._active_source_id,
                "rowCount": len(parsed.rows) if parsed else 0,
                "columnCount": len(parsed.headers) if parsed else 0,
                "headers": list(parsed.headers) if parsed else [],
                "columnTypes": {},
                "calculatedColumns": [],
            })

        self._table_catalog = catalog
        self._model_tables = [
            str(table["name"]) for table in catalog if table["loadEnabled"]
        ]
        self._model_relationships = [
            self._model_relationship_label(relationship)
            for relationship in model.get("relationships", [])
        ]

    @staticmethod
    def _source_metadata_warning(sources: list[dict[str, Any]]) -> str:
        notices = []
        unsupported = sorted(
            {str(item.get("kind", "unknown")) for item in sources
             if item.get("kind") not in SUPPORTED_SOURCE_KINDS | {"inline"}}
        )
        if unsupported:
            notices.append(f"Unsupported source type(s): {', '.join(unsupported)}.")
        return "\n".join(notices)

    def _compose_source_warning(self) -> str:
        warnings = list(self._source_load_errors.values())
        metadata_warning = self._source_metadata_warning(self._project.get("data_sources", []))
        if metadata_warning and metadata_warning not in warnings:
            warnings.append(metadata_warning)
        return "\n".join(warnings)

    def _chart_key(self, visual_name: str) -> str | None:
        return {"Monthly revenue": "monthly", "Region revenue": "region"}.get(visual_name)

    def _set_status(self, message: str) -> None:
        self._status_message = message
        self.statusChanged.emit(message)

    # Advanced Authoring Commands

    @Slot()
    def copy_selected_visual(self) -> None:
        if not self._selected_visual: return
        page = self._active_page()
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == self._selected_visual), None)
        if visual:
            from copy import deepcopy
            self._clipboard_visual_config = deepcopy(visual)
            self._set_status(f"Copied visual {self._selected_visual}")

    @Slot()
    def cut_selected_visual(self) -> None:
        if not self._selected_visual: return
        self.copy_selected_visual()
        for v in self._active_page().get("visuals", []):
             if isinstance(v, dict) and v.get("title") == self._selected_visual:
                 self.remove_visual(v.get("id"))
                 break
        self._set_status("Cut visual")

    @Slot()
    def paste_visual(self) -> None:
        if not self._clipboard_visual_config: return
        from uuid import uuid4
        from copy import deepcopy
        page = self._active_page()
        visuals = page.setdefault("visuals", [])
        new_visual = deepcopy(self._clipboard_visual_config)
        new_visual["id"] = str(uuid4())
        
        # Offset coordinates by a small amount to make it visible it was pasted
        new_visual["x"] = new_visual.get("x", 10) + 20
        new_visual["y"] = new_visual.get("y", 10) + 20
        
        # Deal with duplicate titles
        base_title = new_visual.get("title", "Visual")
        title = base_title
        num = 1
        while any(isinstance(v, dict) and v.get("title") == title for v in visuals):
            num += 1
            title = f"{base_title} ({num})"
        new_visual["title"] = title
        
        visuals.append(new_visual)
        self._dirty = True
        self._selected_visual = title
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status("Pasted visual")

    @Slot()
    def copy_format(self) -> None:
        if not self._selected_visual: return
        page = self._active_page()
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == self._selected_visual), None)
        if visual:
            from copy import deepcopy
            self._clipboard_format_config = {
                "color": visual.get("color"),
                "type": visual.get("type")
            }
            self._format_painter_active = True
            self._set_status("Format Copied - Select another visual to paint")

    @Slot(str)
    def apply_format_painter(self, visual_title: str) -> None:
        if not self._format_painter_active or not self._clipboard_format_config: return
        page = self._active_page()
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == visual_title:
                if self._clipboard_format_config.get("color"):
                    visual["color"] = self._clipboard_format_config["color"]
                if self._clipboard_format_config.get("type"):
                    visual["type"] = self._clipboard_format_config["type"]
                self._dirty = True
                self._format_painter_active = False # One time use
                self._refresh_report()
                self.stateChanged.emit()
                self._set_status(f"Format applied to {visual_title}")
                break

    @Slot()
    def bring_forward(self) -> None:
        if not self._selected_visual: return
        page = self._active_page()
        visuals = page.setdefault("visuals", [])
        idx = next((i for i, v in enumerate(visuals) if isinstance(v, dict) and v.get("title") == self._selected_visual), -1)
        if idx >= 0 and idx < len(visuals) - 1:
            visuals[idx], visuals[idx + 1] = visuals[idx + 1], visuals[idx]
            self._dirty = True
            self.stateChanged.emit()

    @Slot()
    def send_backward(self) -> None:
        if not self._selected_visual: return
        page = self._active_page()
        visuals = page.setdefault("visuals", [])
        idx = next((i for i, v in enumerate(visuals) if isinstance(v, dict) and v.get("title") == self._selected_visual), -1)
        if idx > 0:
            visuals[idx], visuals[idx - 1] = visuals[idx - 1], visuals[idx]
            self._dirty = True
            self.stateChanged.emit()

    @Slot()
    def bring_to_front(self) -> None:
        if not self._selected_visual: return
        page = self._active_page()
        visuals = page.setdefault("visuals", [])
        idx = next((i for i, v in enumerate(visuals) if isinstance(v, dict) and v.get("title") == self._selected_visual), -1)
        if idx >= 0 and idx != len(visuals) - 1:
            item = visuals.pop(idx)
            visuals.append(item)
            self._dirty = True
            self.stateChanged.emit()

    @Slot()
    def group_visuals(self) -> None:
        # Stub for multi-select grouping
        self._set_status("Grouping requires multi-select (Not implemented in preview)")

    @Slot()
    def ungroup_visuals(self) -> None:
        # Stub for multi-select grouping
        self._set_status("Ungrouping requires groups (Not implemented in preview)")

    @Slot()
    def send_to_back(self) -> None:
        if not self._selected_visual: return
        page = self._active_page()
        visuals = page.setdefault("visuals", [])
        idx = next((i for i, v in enumerate(visuals) if isinstance(v, dict) and v.get("title") == self._selected_visual), -1)
        if idx > 0:
            item = visuals.pop(idx)
            visuals.insert(0, item)
            self._dirty = True
            self.stateChanged.emit()
