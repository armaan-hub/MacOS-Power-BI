"""Python state and project lifecycle exposed to the Qt Quick interface."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import calendar
import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, DecimalException
import json
import math
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
    QUrl,
)
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox

from analytics_studio.project import (
    FORMAT_VERSION,
    ProjectFileError,
    REPORT_THEMES,
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
from analytics_studio.query_parameters import parameter_references, parameter_values
from analytics_studio.query_functions import function_references
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
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    m_compatibility_issues,
    m_script_matches_steps,
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
    rename_table_references,
    tokenize,
    validate_calculated_columns,
)
from analytics_studio.query_engine import QueryError, append_candidates, merge_candidates
from analytics_studio.recent_sources import RecentSourcesStore
from analytics_studio.sql_server import SQLServerError, read_sql_server_object
from analytics_studio.sql_server_credentials import (
    CredentialStoreError,
    credential_account as sql_server_credential_account,
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
    _relationship_value_key,
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
    infer_column_types,
    validate_steps,
)


PREVIEW_ROW_LIMIT = 500
CHART_TYPES = {"column", "bar", "line"}
CHART_VISUALS = {"Monthly revenue", "Region revenue"}


def _rename_table_references_in_project(
    project: dict[str, Any], old_name: str, new_name: str
) -> None:
    """Preserve DAX and calculated-table bindings when a model table is renamed."""
    model = project.get("model", {})
    for measure in model.get("measures", []):
        measure["expression"] = rename_table_references(
            measure["expression"], old_name, new_name
        )
    for table in model.get("tables", []):
        for calculated_column in table.get("calculated_columns", []):
            calculated_column["expression"] = rename_table_references(
                calculated_column["expression"], old_name, new_name
            )
    for source in project.get("data_sources", []):
        definition = source.get("query_definition", {})
        if (
            definition.get("operation") == "calculated_table"
            and str(definition.get("source_table", "")).casefold() == old_name.casefold()
        ):
            definition["source_table"] = new_name
            definition["expression"] = rename_table_references(
                definition["expression"], old_name, new_name
            )


def _query_deletion_blockers(
    project: dict[str, Any],
    deleted_source_ids: set[str],
    *,
    active_source_id: str | None,
) -> list[str]:
    """Describe project objects that would be left pointing at deleted tables."""
    if not deleted_source_ids:
        return []
    model = project.get("model", {})
    sources_by_id = {
        str(source.get("id", "")): source
        for source in project.get("data_sources", [])
    }
    tables_by_source = {
        str(table.get("source_id") or table.get("id")): table
        for table in model.get("tables", [])
    }
    deleted_tables = {
        source_id: tables_by_source.get(source_id)
        for source_id in deleted_source_ids
    }
    table_ids = set(deleted_source_ids)
    table_names: dict[str, str] = {}
    table_headers: dict[str, set[str]] = {}
    for source_id, table in deleted_tables.items():
        source = sources_by_id.get(source_id, {})
        if table is not None:
            table_ids.add(str(table.get("id", "")))
        table_names[source_id] = str(
            (table or {}).get("name")
            or source.get("query_name")
            or source.get("name")
            or source_id
        )
        table_headers[source_id] = {
            str(column).casefold()
            for column in (table or {}).get("column_types", {})
        }

    blockers: list[str] = []
    for source in project.get("data_sources", []):
        source_id = str(source.get("id", ""))
        if source_id in deleted_source_ids or source.get("kind") != "query":
            continue
        dependencies = {
            str(item)
            for item in source.get("query_definition", {}).get("source_ids", [])
        }
        missing = dependencies & deleted_source_ids
        if missing:
            names = ", ".join(table_names.get(item, item) for item in sorted(missing))
            blockers.append(
                f"query {source.get('query_name', source.get('name', source_id))!r} depends on {names}"
            )

    for relationship in model.get("relationships", []):
        endpoints = {
            str(relationship.get("from_table_id", "")),
            str(relationship.get("to_table_id", "")),
        }
        legacy_endpoints = {
            str(relationship.get("from", "")),
            str(relationship.get("to", "")),
        }
        legacy_match = any(
            endpoint == table_names.get(source_id, "")
            or endpoint == source_id
            or endpoint.startswith((
                table_names.get(source_id, "") + ".",
                table_names.get(source_id, "") + "[",
            ))
            for source_id in deleted_source_ids
            for endpoint in legacy_endpoints
        )
        if endpoints & table_ids or legacy_match:
            blockers.append("a saved model relationship uses the table")
            break

    def walk_table_references(value: Any) -> bool:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"table_id", "tableId"} and str(child) in table_ids:
                    return True
                if walk_table_references(child):
                    return True
        elif isinstance(value, list):
            return any(walk_table_references(item) for item in value)
        return False

    report = project.get("report", {})
    if walk_table_references(report):
        blockers.append("a report filter, sort, or visual binding uses the table")

    # Legacy and current visuals can bind through plain field names. The active
    # table supplies their implicit binding when a visual has no table_id.
    if active_source_id in deleted_source_ids:
        active_headers = table_headers.get(str(active_source_id), set())

        def uses_active_table(binding: Any) -> bool:
            if isinstance(binding, str):
                return binding.casefold() in active_headers
            if isinstance(binding, dict):
                bound_table_id = binding.get("table_id") or binding.get("tableId")
                if bound_table_id:
                    return str(bound_table_id) in table_ids
                return str(binding.get("column", "")).casefold() in active_headers
            if isinstance(binding, (list, tuple)):
                if len(binding) >= 2 and str(binding[0]) in table_ids:
                    return str(binding[0]) in table_ids
                return any(uses_active_table(item) for item in binding)
            return False

        for page in report.get("pages", []):
            for visual in page.get("visuals", []):
                if visual.get("table_id"):
                    continue
                fields = visual.get("fields", {})
                if isinstance(fields, dict) and any(
                    uses_active_table(binding)
                    for well in fields.values()
                    if isinstance(well, (list, tuple))
                    for binding in well
                ):
                    blockers.append(
                        f"visual {visual.get('title', 'Untitled')!r} uses a field from the active table"
                    )
                    break
            if blockers and blockers[-1].startswith("visual "):
                break

    for source in project.get("data_sources", []):
        if str(source.get("id", "")) in deleted_source_ids:
            continue
        definition = source.get("query_definition", {})
        source_table = str(definition.get("source_table", "")).casefold()
        if source_table and any(
            source_table == name.casefold() for name in table_names.values()
        ):
            blockers.append(
                f"calculated table {source.get('query_name', source.get('name', 'query'))!r} binds to the table name"
            )

    def dax_references(expression: Any) -> list[tuple[str, str]]:
        try:
            return [
                token.value.split("\0", 1)
                for token in tokenize(str(expression))
                if token.kind == "reference"
            ]
        except MeasureError:
            return []

    for measure in model.get("measures", []):
        references = dax_references(measure.get("expression", ""))
        for source_id in deleted_source_ids:
            table_name = table_names[source_id]
            if any(
                (table and table.casefold() == table_name.casefold())
                or (not table and column.casefold() in table_headers[source_id])
                for table, column in references
            ):
                blockers.append(f"measure {measure.get('name', 'Measure')!r} references {table_name!r}")
                break

    for table in model.get("tables", []):
        table_source_id = str(table.get("source_id") or table.get("id", ""))
        if table_source_id in deleted_source_ids:
            continue
        for calculated_column in table.get("calculated_columns", []):
            references = dax_references(calculated_column.get("expression", ""))
            for source_id in deleted_source_ids:
                table_name = table_names[source_id]
                if any(
                    referenced_table
                    and referenced_table.casefold() == table_name.casefold()
                    for referenced_table, _column in references
                ):
                    blockers.append(
                        "calculated column "
                        f"{calculated_column.get('name', 'Calculated column')!r} "
                        f"references {table_name!r}"
                    )
                    break
    return list(dict.fromkeys(blockers))
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
    "report_month": "month is",
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
_VISUAL_FIELD_AGGREGATIONS = {
    "sum": "Sum",
    "count": "Count",
    "average": "Average",
}
_VISUAL_MEASURE_PREFIX = "__dax_measure__:"


def _visual_measure_name(binding: Any) -> str | None:
    value = str(binding)
    if not value.startswith(_VISUAL_MEASURE_PREFIX):
        return None
    name = value[len(_VISUAL_MEASURE_PREFIX):]
    return name or None


def _visual_measure_binding(name: str) -> str:
    return f"{_VISUAL_MEASURE_PREFIX}{name}"


def _open_external_url(url: QUrl) -> bool:
    return QDesktopServices.openUrl(url)


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
    if operator == "report_month":
        return _report_month(value) == str(clause.get("value", ""))
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
        try:
            key = _relationship_value_key(row.get(column), column_type)
        except RelationshipError as exc:
            raise RelationshipError(f"{table_name}[{column}] {exc}") from exc
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
        self._raw_candidates: dict[str, ImportCandidate] = {}
        self._source_load_errors: dict[str, str] = {}
        self._sql_server_passwords: dict[str, str] = {}
        self._source_warning = ""
        self._field_query = ""
        self._current_region: str | None = None
        self._selected_visual = ""
        self._selected_visual_ids: list[str] = []
        self._creating_visual = False
        self._clipboard_visual_config: dict[str, Any] | None = None
        self._clipboard_format_config: dict[str, Any] | None = None
        self._format_painter_active = False
        self._status_message = "Ready · new project"
        self._kpis: dict[str, str] = {}
        self._region_column: str | None = None
        self._measure_values: dict[str, str] = {}
        self._measure_errors: dict[str, str] = {}
        self._visual_kpis: dict[str, str] = {}
        self._cross_filters: dict[str, list[str]] = {}
        self._filter_context_error = ""
        self._report_filter_context_cache: dict[
            tuple[str | None, bool],
            tuple[
                dict[str, list[dict[str, Any]]],
                list[dict[str, Any]],
                set[str],
                str,
            ],
        ] = {}
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
        if v_type == "scatter":
            wells = ["X-axis", "Y-axis", "Legend", "Details", "Tooltips"]
        elif v_type == "waterfall":
            wells = ["X-axis", "Y-axis", "Tooltips"]
        elif v_type == "treemap":
            wells = ["X-axis", "Y-axis", "Tooltips"]
        elif v_type == "matrix":
            wells = ["Rows", "Columns", "Values", "Tooltips"]
        elif v_type == "lineClusteredColumn":
            wells = ["X-axis", "Column Y-axis", "Line Y-axis", "Tooltips"]
        elif v_type == "gauge":
            wells = ["Value", "Minimum", "Maximum", "Target", "Tooltips"]
        elif v_type == "kpi":
            wells = ["Indicator", "Trend axis", "Target goals", "Tooltips"]
        elif v_type == "map":
            wells = ["Location", "Latitude", "Longitude", "Size", "Legend", "Tooltips"]
        elif v_type in {
            "column", "bar", "stackedBar", "stackedColumn", "bar100", "column100",
            "stackedArea", "area100",
            "line", "area", "pie", "donut", "funnel", "ribbon",
        }:
            wells = ["X-axis", "Y-axis", "Legend", "Tooltips"]
        elif v_type in {"shape", "text_box", "image"}:
            return []
        else:
            wells = ["Fields", "Tooltips"]
            
        assigned_fields = visual.get("fields", {})
        return [
            {
                "name": well,
                "fields": assigned_fields.get(well, []),
                "aggregations": dict(visual.get("field_aggregations", {})),
            }
            for well in wells
        ]

    @Property("QVariantList", notify=stateChanged)
    def activeVisualInteractions(self) -> list[dict[str, object]]:  # noqa: N802
        page = self._active_page()
        if not page or not self._selected_visual:
            return []
        visuals = [item for item in page.get("visuals", []) if isinstance(item, dict)]
        source = next((item for item in visuals if item.get("title") == self._selected_visual), None)
        if source is None or source.get("type") == "card":
            return []
        result = []
        for target in visuals:
            if target is source or not target.get("title"):
                continue
            mode = self._visual_interaction_mode(source, target)
            result.append({
                "title": str(target["title"]),
                "mode": mode,
                "mode_index": {"filter": 0, "highlight": 1, "none": 2}[mode],
            })
        return result

    @staticmethod
    def _visual_persistence_id(visual: dict[str, Any]) -> str:
        return str(visual.get("id") or visual.get("title") or "")

    def _visual_interaction_mode(
        self, source: dict[str, Any], target: dict[str, Any]
    ) -> str:
        page = self._active_page()
        source_id = self._visual_persistence_id(source)
        target_id = self._visual_persistence_id(target)
        for interaction in (page.get("visual_interactions", []) if page else []):
            if (
                interaction.get("source_visual_id") == source_id
                and interaction.get("target_visual_id") == target_id
            ):
                mode = str(interaction.get("mode", "filter"))
                return mode if mode in {"filter", "highlight", "none"} else "filter"
        return "filter"

    @Slot(str, str, str)
    def set_visual_interaction(
        self, source_title: str, target_title: str, mode: str
    ) -> None:
        mode = mode.strip().casefold()
        page = self._active_page()
        visuals = [item for item in (page.get("visuals", []) if page else []) if isinstance(item, dict)]
        source = next((item for item in visuals if item.get("title") == source_title), None)
        target = next((item for item in visuals if item.get("title") == target_title), None)
        if source is None or target is None or source is target:
            self._set_status("Choose two different visuals on this page.")
            return
        if source.get("type") == "card":
            self._set_status("A Card visual has no category selection to send to other visuals.")
            return
        if mode not in {"filter", "highlight", "none"}:
            self._set_status("Visual interactions support Filter, Highlight, or None.")
            return
        source_id = self._visual_persistence_id(source)
        target_id = self._visual_persistence_id(target)
        interactions = page.setdefault("visual_interactions", [])
        interaction = next((
            item for item in interactions
            if item.get("source_visual_id") == source_id
            and item.get("target_visual_id") == target_id
        ), None)
        if mode == "filter":
            if interaction is None:
                return
            interactions.remove(interaction)
        elif interaction is not None and interaction.get("mode") == mode:
            return
        elif interaction is None:
            interactions.append({
                "source_visual_id": source_id,
                "target_visual_id": target_id,
                "mode": mode,
            })
        else:
            interaction["mode"] = mode
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str, str, result=str)
    def visualFieldAggregation(self, well_name: str, field_name: str) -> str:  # noqa: N802
        if _visual_measure_name(field_name) is not None:
            return ""
        if well_name not in {
            "Y-axis", "Column Y-axis", "Line Y-axis", "Value", "Minimum",
            "Maximum", "Target", "Indicator", "Target goals", "Fields", "Values",
        } or not self._selected_visual:
            return ""
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        if visual is None or (
            well_name in {"Y-axis", "Column Y-axis", "Line Y-axis"}
            and field_name not in visual.get("fields", {}).get(well_name, [])
        ) or (
            well_name in {"Value", "Minimum", "Maximum", "Target"}
            and (
                visual.get("type") != "gauge"
                or field_name not in visual.get("fields", {}).get(well_name, [])
            )
        ) or (
            well_name in {"Indicator", "Target goals"}
            and (
                visual.get("type") != "kpi"
                or field_name not in visual.get("fields", {}).get(well_name, [])
            )
        ) or (
            well_name == "Fields" and (
                visual.get("type") != "card"
                or field_name not in visual.get("fields", {}).get(well_name, [])
            )
        ) or (
            well_name == "Values" and (
                visual.get("type") != "matrix"
                or field_name not in visual.get("fields", {}).get(well_name, [])
            )
        ):
            return ""
        key = str(visual.get("field_aggregations", {}).get(field_name, "sum")).casefold()
        return _VISUAL_FIELD_AGGREGATIONS.get(key, "Sum")

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
            
        groups = [
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
                    {"key": "color", "label": "Primary Color", "type": "color", "value": visual.get("color", "#0078D4")},
                    {"key": "show_data_labels", "label": "Data Labels", "type": "boolean", "value": visual.get("show_data_labels", False)},
                    {"key": "show_legend", "label": "Legend", "type": "boolean", "value": visual.get("show_legend", False)},
                ]
            },
            {
                "name": "Action",
                "properties": [
                    {"key": "actionUrl", "label": "Web URL", "type": "string", "value": visual.get("actionUrl", "")},
                    {"key": "text", "label": "Button Text", "type": "string", "value": visual.get("text", "")},
                ]
            } if visual.get("type") == "button" else None
        ]
        if visual.get("type") == "text_box":
            groups.insert(1, {
                "name": "Text",
                "properties": [
                    {"key": "text", "label": "Text", "type": "string", "value": visual.get("text", "")},
                ],
            })
        if visual.get("type") == "image":
            groups.insert(1, {
                "name": "Image",
                "properties": [
                    {"key": "image_path", "label": "Image path", "type": "string", "value": visual.get("image_path", "")},
                ],
            })

        return [group for group in groups if group is not None]

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
        fields = [field for field in self._headers if query in field.casefold()]
        measures = [
            _visual_measure_binding(str(item["name"]))
            for item in self._project.get("model", {}).get("measures", [])
            if not item.get("is_hidden", False)
            if query in f"measure {item['name']}".casefold()
        ]
        return [*fields, *measures]

    @Property("QVariantList", notify=stateChanged)
    def activeVisualFieldOptions(self) -> list[str]:  # noqa: N802
        options = self.filteredFields
        page = self._active_page()
        if not self._selected_visual or page is None:
            return options
        visual = next((
            item for item in page.get("visuals", [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        if visual is not None and visual.get("type") == "slicer":
            return [item for item in options if _visual_measure_name(item) is None]
        return options

    @Slot(str, result=str)
    def visualFieldLabel(self, binding: str) -> str:  # noqa: N802
        measure_name = _visual_measure_name(binding)
        return f"Measure · {measure_name}" if measure_name else binding

    @Slot(str, result=bool)
    def visualFieldIsMeasure(self, binding: str) -> bool:  # noqa: N802
        return _visual_measure_name(binding) is not None

    @Property("QVariantMap", notify=stateChanged)
    def reportKpis(self) -> dict[str, str]:  # noqa: N802
        return dict(self._kpis)

    @Property("QVariantMap", notify=stateChanged)
    def visualKpis(self) -> dict[str, str]:  # noqa: N802
        return dict(self._visual_kpis)

    @Property("QVariantList", notify=stateChanged)
    def reportKpiNames(self) -> list[str]:  # noqa: N802
        visible_measures = [
            str(item["name"])
            for item in self._project.get("model", {}).get("measures", [])
            if not item.get("is_hidden", False)
        ]
        return ["Revenue", "Cost", "Margin", "Units", "Orders", *visible_measures]

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
    def visualSeries(self, visual_name: str) -> list[dict[str, object]]:
        series = self._generate_dynamic_visual_series(visual_name)
        return [dict(item) for item in series]

    @Slot(str, result="QVariantList")
    def visualLineSeries(self, visual_name: str) -> list[dict[str, object]]:  # noqa: N802
        series = self._generate_dynamic_visual_series(
            visual_name, value_well="Line Y-axis"
        )
        return [dict(item) for item in series]

    @Slot(str, result="QVariantList")
    def visualLineHighlightSeries(self, visual_name: str) -> list[dict[str, object]]:  # noqa: N802
        if not self.visualHighlightSeries(visual_name):
            return []
        series = self._generate_dynamic_visual_series(
            visual_name, include_highlights=True, value_well="Line Y-axis"
        )
        return [dict(item) for item in series]

    @Slot(str, bool, result="QVariantMap")
    def visualGaugeData(
        self, visual_name: str, include_highlights: bool = False
    ) -> dict[str, object]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None or visual.get("type") != "gauge":
            return {
                "value": 0.0, "minimum": 0.0, "maximum": 1.0,
                "target": None, "highlight_value": None, "has_value": False,
            }

        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        rows_by_table, measure_context, filter_table_ids = self._report_filter_context(
            visual_name, include_highlights=include_highlights
        )
        source_rows = rows_by_table.get(bound_table_id, [])
        fields = visual.get("fields", {})

        def aggregate_well(well_name: str) -> Decimal | None:
            bindings = fields.get(well_name, [])
            if not isinstance(bindings, list) or not bindings:
                return None
            binding = bindings[0]
            if isinstance(binding, dict):
                column = str(binding.get("column", ""))
            elif isinstance(binding, (list, tuple)):
                column = str(binding[1] if len(binding) > 1 else (binding[0] if binding else ""))
            else:
                column = str(binding)
            if not column:
                return None
            measure_name = _visual_measure_name(column)
            if measure_name:
                try:
                    return self._measure_value_for_visual_group(
                        measure_name, measure_context, filter_table_ids, {},
                        bound_table_id,
                    )
                except (MeasureError, KeyError, TypeError, ValueError):
                    return None
            aggregation = str(visual.get("field_aggregations", {}).get(column, "sum")).casefold()
            if aggregation not in _VISUAL_FIELD_AGGREGATIONS:
                aggregation = "sum"
            raw_values = [row.get(column) for row in source_rows]
            if aggregation == "count":
                count = sum(value is not None and bool(str(value).strip()) for value in raw_values)
                return Decimal(count) if count else Decimal(0)
            numbers = [number for value in raw_values if (number := _report_number(value)) is not None]
            if not numbers:
                return None
            total = sum(numbers, Decimal(0))
            return total / len(numbers) if aggregation == "average" else total

        value = aggregate_well("Value")
        if value is None:
            return {
                "value": 0.0, "minimum": 0.0, "maximum": 1.0,
                "target": None, "highlight_value": None, "has_value": False,
            }
        minimum = aggregate_well("Minimum")
        maximum = aggregate_well("Maximum")
        target = aggregate_well("Target")
        result = {
            "value": float(value),
            "minimum": float(minimum) if minimum is not None else 0.0,
            "maximum": float(maximum) if maximum is not None else float(max(Decimal(1), value)),
            "target": float(target) if target is not None else None,
            "has_value": True,
        }
        if not include_highlights:
            highlight = self.visualGaugeHighlightData(visual_name)
            result["highlight_value"] = highlight.get("value")
        return result

    @Slot(str, result="QVariantMap")
    def visualGaugeHighlightData(self, visual_name: str) -> dict[str, object]:  # noqa: N802
        page = self._active_page()
        target = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if target is None or target.get("type") != "gauge":
            return {"has_value": False}
        has_highlight = any(
            selected
            and (source := next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == source_title
            ), None)) is not None
            and self._visual_interaction_mode(source, target) == "highlight"
            for source_title, selected in self._cross_filters.items()
        )
        if not has_highlight:
            return {"has_value": False}
        return self.visualGaugeData(visual_name, True)

    @Slot(str, bool, result="QVariantMap")
    def visualKpiData(
        self, visual_name: str, include_highlights: bool = False
    ) -> dict[str, object]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        empty = {
            "field": "", "trend_field": "", "value": 0.0, "target": None,
            "trend": [], "highlight_value": None, "has_value": False,
        }
        if visual is None or visual.get("type") != "kpi":
            return empty

        def field_name(well_name: str) -> str:
            bindings = visual.get("fields", {}).get(well_name, [])
            if not isinstance(bindings, list) or not bindings:
                return ""
            binding = bindings[0]
            if isinstance(binding, dict):
                return str(binding.get("column", ""))
            if isinstance(binding, (list, tuple)):
                return str(binding[1] if len(binding) > 1 else (binding[0] if binding else ""))
            return str(binding)

        indicator_field = field_name("Indicator")
        trend_field = field_name("Trend axis")
        target_field = field_name("Target goals")
        if not indicator_field or not trend_field:
            return empty

        values = self._generate_dynamic_visual_series(
            visual_name, include_highlights=include_highlights
        )
        if not values:
            return empty
        targets = self._generate_dynamic_visual_series(
            visual_name,
            include_highlights=include_highlights,
            value_well="Target goals",
        ) if target_field else []
        targets_by_label = {str(item["label"]): float(item["value"]) for item in targets}
        trend = [
            {
                "label": str(item["label"]),
                "value": float(item["value"]),
                "target": targets_by_label.get(str(item["label"])),
            }
            for item in values
        ]
        latest = trend[-1]
        result: dict[str, object] = {
            "field": self.visualFieldLabel(indicator_field),
            "trend_field": trend_field,
            "value": latest["value"],
            "target": latest["target"],
            "label": latest["label"],
            "trend": trend,
            "highlight_value": None,
            "has_value": True,
        }
        if not include_highlights and self.visualHighlightSeries(visual_name):
            highlighted = self.visualKpiData(visual_name, True)
            if highlighted.get("has_value"):
                result["highlight_value"] = highlighted.get("value")
        return result

    @Slot(str, bool, result="QVariantList")
    def visualMapData(
        self, visual_name: str, include_highlights: bool = False
    ) -> list[dict[str, object]]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None or visual.get("type") != "map":
            return []

        def field_name(well_name: str) -> str:
            bindings = visual.get("fields", {}).get(well_name, [])
            if not isinstance(bindings, list) or not bindings:
                return ""
            binding = bindings[0]
            if isinstance(binding, dict):
                return str(binding.get("column", ""))
            if isinstance(binding, (list, tuple)):
                return str(binding[1] if len(binding) > 1 else (binding[0] if binding else ""))
            return str(binding)

        latitude_field = field_name("Latitude")
        longitude_field = field_name("Longitude")
        if not latitude_field or not longitude_field:
            return []
        if include_highlights:
            has_highlight = any(
                selected
                and (source := next((
                    item for item in (page.get("visuals", []) if page else [])
                    if isinstance(item, dict) and item.get("title") == source_title
                ), None)) is not None
                and self._visual_interaction_mode(source, visual) == "highlight"
                for source_title, selected in self._cross_filters.items()
            )
            if not has_highlight:
                return []

        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        rows_by_table, _, _ = self._report_filter_context(
            visual_name, include_highlights=include_highlights
        )
        rows = rows_by_table.get(bound_table_id, [])
        location_field = field_name("Location")
        size_field = field_name("Size")
        legend_field = field_name("Legend")
        points: list[dict[str, object]] = []
        for row in rows:
            latitude = _report_number(row.get(latitude_field))
            longitude = _report_number(row.get(longitude_field))
            if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                continue
            location_value = row.get(location_field) if location_field else None
            label = (
                str(location_value).strip()
                if location_value is not None and str(location_value).strip()
                else f"{float(latitude):.4g}, {float(longitude):.4g}"
            )
            size = _report_number(row.get(size_field)) if size_field else None
            legend_value = row.get(legend_field) if legend_field else None
            group = (
                "(Blank)" if legend_field and (legend_value is None or not str(legend_value).strip())
                else str(legend_value) if legend_field else ""
            )
            points.append({
                "id": f"{label}|{latitude}|{longitude}|{group}",
                "label": label,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "size": max(0.0, float(size)) if size is not None else 1.0,
                "group": group,
            })
        return points

    @Slot(str, bool, result="QVariantList")
    def visualScatterData(
        self, visual_name: str, include_highlights: bool = False
    ) -> list[dict[str, object]]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None or visual.get("type") != "scatter":
            return []

        def field_name(well_name: str) -> str:
            bindings = visual.get("fields", {}).get(well_name, [])
            if not isinstance(bindings, list) or not bindings:
                return ""
            binding = bindings[0]
            if isinstance(binding, dict):
                return str(binding.get("column", ""))
            if isinstance(binding, (list, tuple)):
                return str(binding[1] if len(binding) > 1 else (binding[0] if binding else ""))
            return str(binding)

        x_field = field_name("X-axis")
        y_field = field_name("Y-axis")
        legend_field = field_name("Legend")
        details_field = field_name("Details")
        if not x_field or not y_field:
            return []

        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        rows_by_table, _, _ = self._report_filter_context(
            visual_name, include_highlights=include_highlights
        )
        rows = rows_by_table.get(bound_table_id, [])
        points: list[dict[str, object]] = []
        for row in rows:
            x_value = _report_number(row.get(x_field))
            y_value = _report_number(row.get(y_field))
            if x_value is None or y_value is None:
                continue
            legend_value = row.get(legend_field) if legend_field else None
            group = (
                "(Blank)" if legend_field and (legend_value is None or not str(legend_value).strip())
                else (str(legend_value) if legend_field else "Series")
            )
            category_value = row.get(details_field) if details_field else (
                legend_value if legend_field else row.get(x_field)
            )
            label = (
                "(Blank)" if category_value is None or not str(category_value).strip()
                else str(category_value)
            )
            x_number, y_number = float(x_value), float(y_value)
            points.append({
                "id": f"{label}|{group}|{x_number}|{y_number}",
                "label": label,
                "group": group,
                "x": x_number,
                "y": y_number,
            })
        return points

    @Slot(str, result="QVariantMap")
    def visualTableData(self, visual_name: str) -> dict[str, object]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None or visual.get("type") != "table":
            return {"columns": [], "rows": [], "total_rows": 0}

        fields = visual.get("fields", {}).get("Fields", [])
        bindings: list[str] = []
        for binding in fields:
            if isinstance(binding, dict):
                field = binding.get("column")
            elif isinstance(binding, (list, tuple)):
                field = binding[1] if len(binding) > 1 else (binding[0] if binding else None)
            else:
                field = binding
            if field is not None and str(field) not in bindings:
                bindings.append(str(field))
        if not bindings:
            return {"columns": [], "rows": [], "total_rows": 0}

        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        rows_by_table, measure_context, filter_table_ids = self._report_filter_context(visual_name)
        source_rows = rows_by_table.get(bound_table_id, [])
        measure_names = {
            binding: _visual_measure_name(binding)
            for binding in bindings
        }
        dimension_columns = [
            binding for binding in bindings if measure_names[binding] is None
        ]
        columns = [measure_names[binding] or binding for binding in bindings]
        model_table = next((
            item for item in self._table_catalog
            if str(item.get("id", "")) == bound_table_id
        ), None)
        candidate = self._loaded_candidates.get(
            str(model_table.get("sourceId", ""))
        ) if model_table else None
        available_columns = set(candidate.headers) if candidate else set()
        missing_dimensions = [
            column for column in dimension_columns
            if column not in available_columns
        ]
        if missing_dimensions:
            names = ", ".join(repr(column) for column in missing_dimensions)
            return {
                "columns": columns,
                "rows": [],
                "total_rows": 0,
                "error": (
                    f"Table fields {names} are no longer available. "
                    "Remove or replace the field after refreshing the source."
                ),
            }
        category_column = dimension_columns[0] if dimension_columns else ""
        highlighted_categories: set[str] = set()
        has_highlight = any(
            selected
            and (source := next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == source_title
            ), None)) is not None
            and self._visual_interaction_mode(source, visual) == "highlight"
            for source_title, selected in self._cross_filters.items()
        )
        if has_highlight and category_column:
            highlight_rows, _, _ = self._report_filter_context(
                visual_name, include_highlights=True
            )
            highlighted_categories = {
                str(row.get(category_column, "") or "")
                for row in highlight_rows.get(bound_table_id, [])
            }

        if not any(measure_names.values()):
            rows = [
                {
                    "values": [
                        "" if row.get(column) is None else str(row.get(column, ""))
                        for column in bindings
                    ],
                    "category": str(row.get(category_column, "") or ""),
                    "highlighted": str(row.get(category_column, "") or "") in highlighted_categories,
                }
                for row in source_rows[:50]
            ]
            return {"columns": columns, "rows": rows, "total_rows": len(source_rows)}

        grouped_rows: dict[tuple[str, ...], dict[str, Any]] = {}
        for row in source_rows:
            key = tuple(
                "" if row.get(column) is None else str(row.get(column, ""))
                for column in dimension_columns
            )
            grouped_rows.setdefault(key, row)
        group_keys = list(grouped_rows)
        if not dimension_columns:
            group_keys = [()]  # A measure-only Table shows its total context.

        rows: list[dict[str, object]] = []
        for key in group_keys[:50]:
            group_filters = dict(zip(dimension_columns, key, strict=True))
            row_values: list[str] = []
            for binding in bindings:
                measure_name = measure_names[binding]
                if measure_name is None:
                    raw_value = grouped_rows[key].get(binding)
                    row_values.append("" if raw_value is None else str(raw_value))
                    continue
                try:
                    value = self._measure_value_for_visual_group(
                        measure_name,
                        measure_context,
                        filter_table_ids,
                        group_filters,
                        bound_table_id,
                    )
                except (MeasureError, KeyError, TypeError, ValueError) as exc:
                    detail = str(exc).strip() or "evaluation failed"
                    return {
                        "columns": columns,
                        "rows": [],
                        "total_rows": 0,
                        "error": f"Measure {measure_name!r} could not be evaluated: {detail}",
                    }
                row_values.append(
                    "" if value is None else _format_report_number(value)
                )

            category = key[0] if key else ""
            rows.append({
                "values": row_values,
                "category": category,
                "highlighted": category in highlighted_categories,
            })
        return {"columns": columns, "rows": rows, "total_rows": len(group_keys)}

    @Slot(str, result="QVariantMap")
    def visualMatrixData(self, visual_name: str) -> dict[str, object]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None or visual.get("type") != "matrix":
            return {"columns": [], "rows": [], "total_rows": 0}

        def field_name(well_name: str) -> str:
            bindings = visual.get("fields", {}).get(well_name, [])
            if not isinstance(bindings, list) or not bindings:
                return ""
            binding = bindings[0]
            if isinstance(binding, dict):
                return str(binding.get("column", ""))
            if isinstance(binding, (list, tuple)):
                return str(binding[1] if len(binding) > 1 else (binding[0] if binding else ""))
            return str(binding)

        row_field = field_name("Rows")
        column_field = field_name("Columns")
        value_field = field_name("Values")
        if not row_field or not column_field or not value_field:
            return {"columns": [], "rows": [], "total_rows": 0}

        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        rows_by_table, measure_context, filter_table_ids = self._report_filter_context(visual_name)
        source_rows = rows_by_table.get(bound_table_id, [])
        measure_name = _visual_measure_name(value_field)
        aggregation = str(visual.get("field_aggregations", {}).get(value_field, "sum")).casefold()
        if aggregation not in _VISUAL_FIELD_AGGREGATIONS:
            aggregation = "sum"

        from collections import defaultdict
        from decimal import Decimal

        grouped: defaultdict[tuple[str, str], Decimal | None] = defaultdict(Decimal)
        counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        row_values: set[str] = set()
        column_values: set[str] = set()
        raw_values_by_cell: dict[tuple[str, str], tuple[set[str], set[str]]] = {}
        for row in source_rows:
            row_key = "(Blank)" if row.get(row_field) is None or not str(row.get(row_field)).strip() else str(row.get(row_field))
            column_key = "(Blank)" if row.get(column_field) is None or not str(row.get(column_field)).strip() else str(row.get(column_field))
            key = (row_key, column_key)
            if measure_name:
                row_raw_values, column_raw_values = raw_values_by_cell.setdefault(
                    key, (set(), set())
                )
                row_raw_values.add("" if row.get(row_field) is None else str(row.get(row_field)))
                column_raw_values.add("" if row.get(column_field) is None else str(row.get(column_field)))
            else:
                raw_value = row.get(value_field)
                if aggregation == "count":
                    if raw_value is None or not str(raw_value).strip():
                        continue
                    amount = Decimal(1)
                else:
                    amount = _report_number(raw_value)
                    if amount is None:
                        continue
                grouped[key] += amount
                counts[key] += 1
            row_values.add(row_key)
            column_values.add(column_key)

        if measure_name:
            for key, (row_raw_values, column_raw_values) in raw_values_by_cell.items():
                try:
                    grouped[key] = self._measure_value_for_visual_group(
                        measure_name,
                        measure_context,
                        filter_table_ids,
                        {
                            row_field: row_raw_values,
                            column_field: column_raw_values,
                        },
                        bound_table_id,
                    )
                    counts[key] = 1
                except (MeasureError, KeyError, TypeError, ValueError):
                    continue

        if aggregation == "average" and not measure_name:
            grouped = defaultdict(
                Decimal,
                {
                    key: total / counts[key]
                    for key, total in grouped.items()
                    if counts[key]
                },
            )

        sorted_rows = sorted(row_values, key=str.casefold)
        sorted_columns = sorted(column_values, key=str.casefold)
        columns = [row_field, *sorted_columns]
        highlighted_categories: set[str] = set()
        has_highlight = any(
            selected
            and (source := next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == source_title
            ), None)) is not None
            and self._visual_interaction_mode(source, visual) == "highlight"
            for source_title, selected in self._cross_filters.items()
        )
        if has_highlight:
            highlight_rows, _, _ = self._report_filter_context(
                visual_name, include_highlights=True
            )
            highlighted_categories = {
                "(Blank)" if row.get(row_field) is None or not str(row.get(row_field)).strip()
                else str(row.get(row_field))
                for row in highlight_rows.get(bound_table_id, [])
            }

        matrix_rows = []
        for row_key in sorted_rows:
            values = [row_key]
            for column_key in sorted_columns:
                cell_key = (row_key, column_key)
                if cell_key not in grouped:
                    values.append("")
                elif grouped[cell_key] is None:
                    values.append("")
                elif not measure_name and aggregation == "count":
                    values.append(f"{int(grouped[cell_key]):,}")
                else:
                    values.append(_format_report_number(grouped[cell_key]))
            matrix_rows.append({
                "values": values,
                "category": row_key,
                "highlighted": row_key in highlighted_categories,
            })
        return {
            "columns": columns,
            "rows": matrix_rows,
            "total_rows": len(matrix_rows),
        }

    @Slot(str, result="QVariantMap")
    def visualCardData(self, visual_name: str) -> dict[str, object]:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None or visual.get("type") != "card":
            return {"label": "", "value": "", "aggregation": "", "highlight_value": "", "has_highlights": False}

        fields = visual.get("fields", {}).get("Fields", [])
        if not fields:
            return {
                "label": visual_name[:-4] if visual_name.endswith(" KPI") else "",
                "value": self._visual_kpis.get(visual_name, "Add a field"),
                "aggregation": "",
                "highlight_value": "",
                "has_highlights": False,
            }
        binding = fields[0]
        if isinstance(binding, dict):
            field_name = str(binding.get("column", ""))
        elif isinstance(binding, (list, tuple)):
            field_name = str(binding[1] if len(binding) > 1 else (binding[0] if binding else ""))
        else:
            field_name = str(binding)
        if not field_name:
            return {"label": "", "value": "—", "aggregation": "", "highlight_value": "", "has_highlights": False}

        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        rows_by_table, measure_context, filter_table_ids = self._report_filter_context(visual_name)
        rows = rows_by_table.get(bound_table_id, [])
        measure_name = _visual_measure_name(field_name)
        if measure_name:
            try:
                value = self._measure_value_for_visual_group(
                    measure_name, measure_context, filter_table_ids, {}, bound_table_id
                )
                formatted = (
                    _format_report_number(value) if value is not None else "—"
                )
            except (MeasureError, KeyError, TypeError, ValueError):
                formatted = "—"
            has_highlights = any(
                selected
                and (source := next((
                    item for item in (page.get("visuals", []) if page else [])
                    if isinstance(item, dict) and item.get("title") == source_title
                ), None)) is not None
                and self._visual_interaction_mode(source, visual) == "highlight"
                for source_title, selected in self._cross_filters.items()
            )
            highlight_value = ""
            if has_highlights:
                _, highlight_context, highlight_filter_ids = self._report_filter_context(
                    visual_name, include_highlights=True
                )
                try:
                    highlight_measure_value = self._measure_value_for_visual_group(
                        measure_name, highlight_context,
                        highlight_filter_ids, {}, bound_table_id,
                    )
                    highlight_value = (
                        _format_report_number(highlight_measure_value)
                        if highlight_measure_value is not None else "—"
                    )
                except (MeasureError, KeyError, TypeError, ValueError):
                    highlight_value = "—"
            return {
                "label": f"Measure · {measure_name}",
                "value": formatted,
                "aggregation": "Measure",
                "highlight_value": highlight_value,
                "has_highlights": has_highlights,
            }
        aggregation = str(visual.get("field_aggregations", {}).get(field_name, "sum")).casefold()
        if aggregation not in _VISUAL_FIELD_AGGREGATIONS:
            aggregation = "sum"

        def aggregate(source_rows: list[dict[str, Any]]) -> str:
            values = [row.get(field_name) for row in source_rows]
            if aggregation == "count":
                count = sum(value is not None and bool(str(value).strip()) for value in values)
                return f"{count:,}"
            numbers = [number for value in values if (number := _report_number(value)) is not None]
            if not numbers:
                return "—"
            total = sum(numbers, Decimal(0))
            if aggregation == "average":
                total /= len(numbers)
            return _format_report_number(total)

        has_highlights = any(
            selected
            and (source := next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == source_title
            ), None)) is not None
            and self._visual_interaction_mode(source, visual) == "highlight"
            for source_title, selected in self._cross_filters.items()
        )
        highlight_value = ""
        if has_highlights:
            highlighted_rows, _, _ = self._report_filter_context(
                visual_name, include_highlights=True
            )
            highlight_value = aggregate(highlighted_rows.get(bound_table_id, []))
        return {
            "label": field_name,
            "value": aggregate(rows),
            "aggregation": aggregation.capitalize(),
            "highlight_value": highlight_value,
            "has_highlights": has_highlights,
        }

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

    @Property("QVariantList", notify=stateChanged)
    def selectedVisualIds(self) -> list[str]:  # noqa: N802
        return list(self._selected_visual_ids)

    @Property(bool, notify=stateChanged)
    def creatingVisual(self) -> bool:  # noqa: N802
        return self._creating_visual

    @Property(str, notify=stateChanged)
    def selectedChartType(self) -> str:  # noqa: N802
        key = self._chart_key(self._selected_visual)
        if key:
            return str(self._project["report"]["chart_types"].get(key, ""))
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        return str(visual.get("type", "")) if visual else ""

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
            transformed = apply_transformations(
                raw_candidate, steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
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
    def modelMeasures(self) -> list[dict[str, Any]]:  # noqa: N802
        measures = self._project.get("model", {}).get("measures", [])
        result = []
        for measure in measures:
            name = str(measure["name"])
            result.append({
                "name": name,
                "expression": str(measure["expression"]),
                "value": self._measure_values.get(name, "—"),
                "error": self._measure_errors.get(name, ""),
                "description": str(measure.get("description", "")),
                "display_folder": str(measure.get("display_folder", "")),
                "is_hidden": bool(measure.get("is_hidden", False)),
            })
        return result

    @Slot(str, result="QVariantList")
    def selectedCrossFiltersForVisual(self, visual_title: str) -> list[str]:
        return self._cross_filters.get(visual_title, [])

    @Slot(str, result="QVariantList")
    def visualHighlightSeries(self, visual_name: str) -> list[dict[str, str | float]]:  # noqa: N802
        page = self._active_page()
        target = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if target is None:
            return []
        has_highlight = any(
            selected
            and (source := next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == source_title
            ), None)) is not None
            and self._visual_interaction_mode(source, target) == "highlight"
            for source_title, selected in self._cross_filters.items()
        )
        return self._generate_dynamic_visual_series(visual_name, include_highlights=True) if has_highlight else []

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
            "powerQueryM": self.power_query_m_editor_dialog,
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

    def _validate_loaded_relationship_candidates(
        self,
        project: dict[str, Any],
        candidate_overrides: dict[str, ImportCandidate] | None = None,
    ) -> None:
        """Validate relationships against the current or staged loaded rows."""
        candidates = dict(self._loaded_candidates)
        candidates.update(candidate_overrides or {})
        relationship_tables = []
        for table in project.get("model", {}).get("tables", []):
            table_id = str(table.get("id", ""))
            source_id = str(table.get("source_id") or table_id)
            candidate = candidates.get(source_id)
            if candidate is None:
                continue
            relationship_tables.append({
                **table,
                "id": table_id,
                "headers": list(candidate.headers),
                "rows": list(candidate.rows),
            })
        # Empty filter roots still check loaded endpoint types and one-side keys.
        propagate_relationship_filters(
            relationship_tables,
            project.get("model", {}).get("relationships", []),
            set(),
        )

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
            connection = dict(source.get("connection", {}))
            credential_ref = str(connection.get("credential_ref", ""))
            still_used = any(
                item.get("kind") == "sql_server"
                and item.get("connection", {}).get("credential_ref") == credential_ref
                for item in self._project.get("data_sources", [])
            )
            if credential_ref and not still_used:
                self._sql_server_passwords.pop(
                    sql_server_credential_account(credential_ref, connection), None
                )
                try:
                    delete_sql_server_password(credential_ref, connection)
                except CredentialStoreError:
                    credential_cleanup_failed = True

        self._loaded_candidates.pop(source_id, None)
        self._raw_candidates.pop(source_id, None)
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
            "column_types": infer_column_types(parsed.headers, parsed.rows),
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
            source_candidate = apply_transformations(
                parsed, transform_steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
            base_types = column_types_after_steps(
                parsed.headers,
                transform_steps,
                output_headers=source_candidate.headers,
                initial_types=table_record["column_types"],
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
        self._raw_candidates[source_id] = parsed
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
            "column_types": infer_column_types(parsed.headers, parsed.rows),
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
            source_candidate = apply_transformations(
                parsed, transform_steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
            base_types = column_types_after_steps(
                parsed.headers,
                transform_steps,
                output_headers=source_candidate.headers,
                initial_types=table_record["column_types"],
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
        self._raw_candidates[source_id] = parsed
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
            "column_types": infer_column_types(parsed.headers, parsed.rows),
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
            source_candidate = apply_transformations(
                parsed, transform_steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
            base_types = column_types_after_steps(
                parsed.headers,
                transform_steps,
                output_headers=source_candidate.headers,
                initial_types=table_record["column_types"],
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
            set_sql_server_password(credential_ref, password, connection)
        except CredentialStoreError as exc:
            QMessageBox.critical(None, "Could not save SQL Server credentials", str(exc))
            return False

        self._sql_server_passwords[
            sql_server_credential_account(credential_ref, connection)
        ] = password
        self._project = next_project
        self._active_source_id = source_id
        self._active_source_path = None
        self._active_source_kind = "sql_server"
        self._active_parser_options = options
        self._source_load_errors.pop(source_id, None)
        self._source_load_errors.pop("__active_selection__", None)
        self._loaded_candidates.update(dependent_candidates)
        self._raw_candidates[source_id] = parsed
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
        self._cross_filters.clear()
        self._selected_visual = ""
        self._selected_visual_ids.clear()
        self._creating_visual = False
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str)
    def selectVisual(self, visual_name: str) -> None:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None:
            return
        visual_id = str(visual.get("id", ""))
        if self._selected_visual == visual_name and self._selected_visual_ids == [visual_id]:
            return
        self._selected_visual = visual_name
        self._selected_visual_ids = [visual_id]
        self._creating_visual = False
        self.stateChanged.emit()

    @Slot(str)
    def toggleVisualSelection(self, visual_name: str) -> None:  # noqa: N802
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == visual_name
        ), None)
        if visual is None:
            return
        self._creating_visual = False
        visual_id = str(visual.get("id", ""))
        if visual_id in self._selected_visual_ids:
            self._selected_visual_ids.remove(visual_id)
            if self._selected_visual == visual_name:
                selected = next((
                    item for item in (page.get("visuals", []) if page else [])
                    if isinstance(item, dict)
                    and str(item.get("id", "")) in self._selected_visual_ids
                ), None)
                self._selected_visual = str(selected.get("title", "")) if selected else ""
        else:
            self._selected_visual_ids.append(visual_id)
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
        for page in candidate.get("report", {}).get("pages", []):
            for visual in page.get("visuals", []):
                image_path = visual.get("image_path") if isinstance(visual, dict) else None
                if isinstance(image_path, str) and image_path:
                    visual["image_path"] = str(resolve_source_path(image_path, path))
        for source in candidate.get("data_sources", []):
            if source.get("kind") not in PATHLESS_SOURCE_KINDS:
                source["path"] = str(resolve_source_path(source["path"], path))

        sources = candidate.get("data_sources", [])
        loaded_candidates: dict[str, ImportCandidate] = {}
        raw_candidates: dict[str, ImportCandidate] = {}
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
                raw_candidates[source_id] = raw
                source_steps = source.get("transform_steps", [])
                if kind in {"odata", "web"} and raw.notices:
                    warnings.extend(
                        f"{source.get('name', source_id)}: {notice}"
                        for notice in raw.notices
                    )
                query_candidate = apply_transformations(
                    raw, source_steps,
                    parameters=parameter_values(candidate.get("query_parameters", []), candidate.get("query_functions", [])),
                )
                initial_types = (
                    self._query_input_column_types(
                        source, candidate, candidate=raw
                    )
                    if kind == "query"
                    else infer_column_types(raw.headers, raw.rows)
                )
                type_map = column_types_after_steps(
                    raw.headers,
                    source_steps,
                    output_headers=query_candidate.headers,
                    initial_types=initial_types,
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
        self._cross_filters.clear()
        self._selected_visual = ""
        self._selected_visual_ids.clear()
        self._creating_visual = False
        self._clipboard_visual_config = None
        self._clipboard_format_config = None
        self._format_painter_active = False
        self._field_query = ""
        self._current_region = None
        self._active_source_id = active_source_id
        self._active_source_path = active_source_path
        self._active_source_kind = active_source_kind
        self._active_parser_options = active_parser_options
        self._loaded_candidates = loaded_candidates
        self._raw_candidates = raw_candidates
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

    def _new_power_query_folder_candidate(
        self,
    ) -> tuple[ImportCandidate, dict[str, Any]] | None:
        """Preview a local folder combine without committing it."""
        selected_folder = QFileDialog.getExistingDirectory(
            None,
            "New Power Query folder source",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected_folder:
            return None
        folder = Path(selected_folder).expanduser().resolve()
        if not folder.is_dir():
            QMessageBox.critical(
                None, "Folder unavailable", f"Choose an existing folder: {folder}"
            )
            return None
        dialog = FolderImportDialog(folder, replacing=False)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return None
        candidate = dialog.candidate
        source_record = {
            "id": str(uuid4()),
            "name": folder.name or str(folder),
            "query_name": folder.name or "Folder data",
            "kind": "folder",
            "path": str(folder),
            "parser_options": dict(candidate.options),
            "transform_steps": [],
        }
        return candidate, source_record

    def _new_power_query_source_candidate(
        self,
    ) -> tuple[ImportCandidate, dict[str, Any]] | None:
        """Preview a local file for Power Query without committing it."""
        file_filter = (
            "Supported data files (*.csv *.xls *.xlsx *.xlsm *.json *.xml *.parquet *.db *.sqlite *.sqlite3);;"
            "CSV files (*.csv);;Excel workbooks (*.xls *.xlsx *.xlsm);;"
            "JSON files (*.json);;XML files (*.xml);;Parquet files (*.parquet);;"
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)"
        )
        selected_path, _ = QFileDialog.getOpenFileName(
            None, "New Power Query source", "", file_filter
        )
        if not selected_path:
            return None
        path = Path(selected_path).expanduser().resolve()
        try:
            source_kind = kind_for_path(path)
        except ValueError as exc:
            QMessageBox.critical(None, "Unsupported data file", str(exc))
            return None

        from analytics_studio.import_preview_dialog import FileImportPreviewDialog

        dialog = FileImportPreviewDialog(path, replacing=False)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return None
        candidate = dialog.candidate
        if candidate.kind != source_kind:
            QMessageBox.critical(
                None,
                "Could not stage source",
                "The source preview does not match the selected file type.",
            )
            return None
        desired_name = (
            str(candidate.options.get("table_name", "")).strip()
            if candidate.kind == "sqlite"
            else path.stem
        ) or path.stem or "New Source"
        source_record = {
            "id": str(uuid4()),
            "name": path.name,
            "query_name": desired_name,
            "kind": candidate.kind,
            "path": str(path),
            "parser_options": dict(candidate.options),
            "transform_steps": [],
        }
        return candidate, source_record

    def _edit_power_query_source_candidate(
        self,
        source_record: dict[str, Any],
    ) -> tuple[ImportCandidate, dict[str, Any]] | None:
        """Preview changed source settings without replacing query identity."""
        source_kind = str(source_record.get("kind", ""))
        if source_kind == "sql_server":
            old_connection = dict(source_record.get("connection", {}))
            old_credential_ref = str(old_connection.get("credential_ref", ""))
            old_account = sql_server_credential_account(
                old_credential_ref, old_connection
            )
            staged_old_password = source_record.get("_staged_password")
            old_password = (
                staged_old_password
                if isinstance(staged_old_password, str) and staged_old_password
                else self._sql_server_passwords.get(old_account, "")
            )
            if not old_password and old_credential_ref:
                try:
                    old_password = get_sql_server_password(
                        old_credential_ref, old_connection
                    ) or ""
                except CredentialStoreError:
                    # The editor can still accept a replacement password. It
                    # will be written to Keychain only after Close & Apply.
                    old_password = ""
            dialog = SQLServerImportDialog(
                source_editing=True,
                initial_connection=old_connection,
                initial_options=dict(source_record.get("parser_options", {})),
                initial_password=old_password,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
                return None
            candidate = dialog.candidate
            settings = dialog.connection_settings
            password = dialog.password
            old_identity = {
                key: old_connection.get(key)
                for key in ("server", "port", "database", "username", "driver", "encrypt")
            }
            updated_record = deepcopy(source_record)
            if settings == old_identity and password == old_password:
                connection = {**settings, "credential_ref": old_credential_ref}
                if not (isinstance(staged_old_password, str) and staged_old_password):
                    updated_record.pop("_staged_password", None)
            else:
                connection = {**settings, "credential_ref": str(uuid4())}
                updated_record["_staged_password"] = password
            updated_record["connection"] = connection
            updated_record["parser_options"] = dict(candidate.options)
            return candidate, updated_record

        if source_kind == "odata":
            dialog = ODataFeedImportDialog(
                source_editing=True,
                initial_connection=dict(source_record.get("connection", {})),
                initial_options=dict(source_record.get("parser_options", {})),
            )
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
                return None
            updated_record = deepcopy(source_record)
            updated_record["connection"] = {"service_root": dialog.service_root}
            updated_record["parser_options"] = dict(dialog.candidate.options)
            return dialog.candidate, updated_record

        if source_kind == "web":
            dialog = WebImportDialog(
                source_editing=True,
                initial_connection=dict(source_record.get("connection", {})),
                initial_options=dict(source_record.get("parser_options", {})),
            )
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
                return None
            updated_record = deepcopy(source_record)
            updated_record["connection"] = {"url": dialog.url}
            updated_record["parser_options"] = dict(dialog.candidate.options)
            return dialog.candidate, updated_record

        if source_kind == "folder":
            current_path = self._resolved_source_path(source_record)
            selected_folder = QFileDialog.getExistingDirectory(
                None,
                "Edit Power Query folder settings",
                str(current_path),
                QFileDialog.Option.ShowDirsOnly,
            )
            if not selected_folder:
                return None
            folder = Path(selected_folder).expanduser().resolve()
            if not folder.is_dir():
                QMessageBox.critical(
                    None,
                    "Could not edit folder settings",
                    f"Choose an existing folder: {folder}",
                )
                return None
            dialog = FolderImportDialog(
                folder,
                replacing=False,
                initial_options=dict(source_record.get("parser_options", {})),
                source_editing=True,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
                return None
            candidate = dialog.candidate
            if candidate.kind != "folder":
                QMessageBox.critical(
                    None,
                    "Could not edit folder settings",
                    "The folder preview does not match the existing folder source.",
                )
                return None
            updated_record = deepcopy(source_record)
            updated_record["path"] = str(folder)
            updated_record["parser_options"] = dict(candidate.options)
            return candidate, updated_record

        file_patterns = {
            "csv": ("CSV files", "*.csv"),
            "excel": ("Excel workbooks", "*.xls *.xlsx *.xlsm"),
            "json": ("JSON files", "*.json"),
            "xml": ("XML files", "*.xml"),
            "parquet": ("Parquet files", "*.parquet"),
            "sqlite": ("SQLite databases", "*.db *.sqlite *.sqlite3"),
        }
        if source_kind not in file_patterns:
            QMessageBox.critical(
                None,
                "Source settings unavailable",
                "Edit Source Settings currently supports CSV, Excel, JSON, XML, Parquet, SQLite, and folder roots.",
            )
            return None
        current_path = self._resolved_source_path(source_record)
        label, pattern = file_patterns[source_kind]
        selected_path, _ = QFileDialog.getOpenFileName(
            None,
            "Edit Power Query source settings",
            str(current_path.parent),
            f"{label} ({pattern});;All files (*)",
        )
        if not selected_path:
            return None
        path = Path(selected_path).expanduser().resolve()
        try:
            if kind_for_path(path) != source_kind:
                raise ValueError(
                    "Choose a file with the same type as the existing Power Query source."
                )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(None, "Could not edit source settings", str(exc))
            return None

        from analytics_studio.import_preview_dialog import FileImportPreviewDialog

        dialog = FileImportPreviewDialog(
            path,
            replacing=False,
            initial_options=dict(source_record.get("parser_options", {})),
            source_editing=True,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return None
        candidate = dialog.candidate
        if candidate.kind != source_kind:
            QMessageBox.critical(
                None,
                "Could not edit source settings",
                "The source preview does not match the existing file type.",
            )
            return None
        updated_record = deepcopy(source_record)
        updated_record["path"] = str(path)
        updated_record["parser_options"] = dict(candidate.options)
        return candidate, updated_record

    def _new_power_query_sql_server_candidate(
        self,
    ) -> tuple[ImportCandidate, dict[str, Any]] | None:
        """Preview SQL Server data and keep its password session-local until Apply."""
        dialog = SQLServerImportDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return None
        candidate = dialog.candidate
        settings = dialog.connection_settings
        options = dict(candidate.options)
        credential_ref = str(uuid4())
        connection = {**settings, "credential_ref": credential_ref}
        source_name = (
            f"{settings['database']}.{options['schema']}.{options['table_name']}"
        )
        source_record = {
            "id": str(uuid4()),
            "name": source_name,
            "query_name": str(options["table_name"]),
            "kind": "sql_server",
            "connection": connection,
            "parser_options": options,
            "transform_steps": [],
            # This field exists only in the editor's in-memory staging state.
            # _commit_transform_session removes it before project validation.
            "_staged_password": dialog.password,
        }
        return candidate, source_record

    def _new_power_query_odata_candidate(
        self,
    ) -> tuple[ImportCandidate, dict[str, Any]] | None:
        """Preview an anonymous OData entity set for staged session import."""
        dialog = ODataFeedImportDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return None
        candidate = dialog.candidate
        options = dict(candidate.options)
        entity_set = str(options.get("entity_set_name", "OData query"))
        source_record = {
            "id": str(uuid4()),
            "name": f"{entity_set} · OData Feed",
            "query_name": entity_set,
            "kind": "odata",
            "connection": {"service_root": dialog.service_root},
            "parser_options": options,
            "transform_steps": [],
        }
        return candidate, source_record

    def _new_power_query_web_candidate(
        self,
    ) -> tuple[ImportCandidate, dict[str, Any]] | None:
        """Preview an anonymous HTTPS source for staged session import."""
        dialog = WebImportDialog()
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return None
        candidate = dialog.candidate
        options = dict(candidate.options)
        query_name = _web_table_name(dialog.url, options)
        source_record = {
            "id": str(uuid4()),
            "name": f"{query_name} · Web",
            "query_name": query_name,
            "kind": "web",
            "connection": {"url": dialog.url},
            "parser_options": options,
            "transform_steps": [],
        }
        return candidate, source_record

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
            "column_types": infer_column_types(parsed.headers, parsed.rows),
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
            source_candidate = apply_transformations(
                parsed, transform_steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
            base_types = column_types_after_steps(
                parsed.headers,
                transform_steps,
                output_headers=source_candidate.headers,
                initial_types=table_record["column_types"],
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
        self._raw_candidates[source_id] = parsed
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
                "column_types": infer_column_types(parsed.headers, parsed.rows),
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
        self._raw_candidates[source_id] = parsed
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
            transformed = apply_transformations(
                candidate, validated_steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
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
        self._raw_candidates[source_id] = candidate
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

    def transform_data_dialog(self, *, open_advanced_editor: bool = False) -> bool:
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
            session_queries = []
            session_outputs = dict(self._loaded_candidates)
            session_type_maps: dict[str, dict[str, str]] = {}
            active_raw_candidate: ImportCandidate | None = None
            active_steps: list[dict[str, Any]] = []
            for query_source in self._source_dependency_order(
                self._project.get("data_sources", [])
            ):
                query_id = str(query_source.get("id", ""))
                if not query_id:
                    continue
                session_outputs.pop(query_id, None)
                query_candidate: ImportCandidate | None = None
                source_column_types: dict[str, str] = {}
                query_steps = validate_steps(
                    query_source.get("transform_steps", [])
                )
                try:
                    frozen_query = (
                        query_source.get("kind") == "query"
                        and not self._source_refresh_included(query_source)
                    )
                    if frozen_query:
                        # Keep an excluded saved query on the exact raw snapshot
                        # used for its last evaluation, even if an upstream file
                        # has changed since then. Users can still edit its steps.
                        query_candidate = self._raw_candidates.get(query_id)
                        if query_candidate is None:
                            query_candidate = self._query_candidate(
                                query_source,
                                self._loaded_candidates,
                                project=self._project,
                            )
                    elif query_source.get("kind") == "query":
                        query_candidate = self._query_candidate(
                            query_source, session_outputs, project=self._project
                        )
                    else:
                        query_candidate = self._session_raw_candidate_for_source(query_source)
                    query_definition = query_source.get("query_definition", {})
                    if query_definition.get("operation") == "reference":
                        dependency_ids = query_definition.get("source_ids", [])
                        if dependency_ids:
                            dependency_id = str(dependency_ids[0])
                            source_column_types = dict(
                                session_type_maps.get(dependency_id, {})
                            )
                            if not source_column_types:
                                source_column_types = self._query_input_column_types(
                                    query_source, self._project
                                )
                    elif query_definition.get("operation") in {"append", "merge"}:
                        source_column_types = self._query_input_column_types(
                            query_source,
                            self._project,
                            candidate=query_candidate,
                            dependency_types=session_type_maps,
                        )
                        if not source_column_types:
                            source_column_types = infer_column_types(
                                query_candidate.headers, query_candidate.rows
                            )
                    else:
                        # Start the session with the same detected types used
                        # by import, project open, and refresh. Otherwise an
                        # unrelated edit in Transform Data turns the preview
                        # type map into all-text and can overwrite the model.
                        source_column_types = infer_column_types(
                            query_candidate.headers, query_candidate.rows
                        )
                    transformed = apply_transformations(
                        query_candidate, query_steps,
                        parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
                    )
                    type_map = column_types_after_steps(
                        query_candidate.headers,
                        query_steps,
                        output_headers=transformed.headers,
                        initial_types=source_column_types,
                    )
                    session_type_maps[query_id] = dict(type_map)
                    if frozen_query:
                        session_output = self._loaded_candidates[query_id]
                    else:
                        session_output, _calculated_types = self._apply_calculated_columns(
                            query_id,
                            transformed,
                            project=self._project,
                            column_types=type_map,
                        )
                except (OSError, QueryError, TransformationError, TypeError, ValueError) as exc:
                    if query_id == self._active_source_id:
                        raise
                    table = self._model_table_for_source(self._project, query_id)
                    query_name = (
                        str(table.get("name", ""))
                        if table is not None
                        else str(query_source.get(
                            "query_name", query_source.get("name", "Current Query")
                        ))
                    )
                    query_group = str(query_source.get("query_group", ""))
                    unavailable = ImportCandidate("query", [], [], {}, [])
                    session_queries.append({
                        "id": query_id,
                        "name": query_name,
                        "display_name": (
                            f"{query_group} / {query_name}" if query_group else query_name
                        ),
                        "description": str(query_source.get("description", "")),
                        "query_group": query_group,
                        "is_saved_query": query_source.get("kind") == "query",
                        "load_enabled": query_source.get("load_enabled", True),
                        "include_in_report_refresh": query_source.get(
                            "include_in_report_refresh", True
                        ),
                        "query_definition": deepcopy(
                            query_source.get("query_definition", {})
                        ),
                        "source_record": deepcopy(query_source),
                        "candidate": unavailable,
                        "source_candidate": query_candidate,
                        "source_column_types": {},
                        "column_types": {},
                        "steps": query_steps,
                        "step_metadata": [],
                        "m_script": query_source.get("m_script"),
                        "is_unavailable": True,
                        "preview_error": str(exc),
                    })
                    continue
                session_outputs[query_id] = session_output
                table = self._model_table_for_source(self._project, query_id)
                query_name = (
                    str(table.get("name", ""))
                    if table is not None
                    else str(
                        query_source.get(
                            "query_name", query_source.get("name", "Current Query")
                        )
                    )
                )
                query_group = str(query_source.get("query_group", ""))
                session_queries.append({
                    "id": query_id,
                    "name": query_name,
                    "display_name": f"{query_group} / {query_name}" if query_group else query_name,
                    "description": str(query_source.get("description", "")),
                    "query_group": query_group,
                    "is_saved_query": query_source.get("kind") == "query",
                    "load_enabled": query_source.get("load_enabled", True),
                    "include_in_report_refresh": query_source.get(
                        "include_in_report_refresh", True
                    ),
                    "query_definition": deepcopy(query_definition),
                    "source_record": deepcopy(query_source),
                    "candidate": query_candidate,
                    "source_column_types": source_column_types,
                    "column_types": dict(type_map),
                    "steps": validate_steps(query_source.get("transform_steps", [])),
                    "step_metadata": deepcopy(query_source.get("step_metadata", [])),
                    "m_script": query_source.get("m_script"),
                })
                if query_id == self._active_source_id:
                    active_raw_candidate = query_candidate
                    active_steps = query_steps
            if active_raw_candidate is None:
                raise ValueError("The active query could not be included in the Power Query session.")
            session_query_ids = {
                str(query.get("id", "")) for query in session_queries
            }
            dialog = TransformDataDialog(
                active_raw_candidate,
                active_steps,
                query_name=self._active_model_table_name(),
                queries=session_queries,
                active_query_id=str(self._active_source_id),
                query_dependents={
                    str(source_id): [
                        str(candidate.get("id", ""))
                        for candidate in self._project.get("data_sources", [])
                        if candidate.get("kind") == "query"
                        and str(source_id) in {
                            str(item)
                            for item in candidate.get("query_definition", {}).get("source_ids", [])
                        }
                    ]
                    for source_id in (
                        str(candidate.get("id", ""))
                        for candidate in self._project.get("data_sources", [])
                    )
                },
                reserved_query_names={
                    str(name).strip()
                    for name in [
                        *(
                            table.get("name", "")
                            for table in self._project.get("model", {}).get("tables", [])
                            if str(table.get("source_id") or table.get("id", ""))
                            not in session_query_ids
                        ),
                        *(
                            source.get("query_name", source.get("name", ""))
                            for source in self._project.get("data_sources", [])
                            if str(source.get("id", "")) not in session_query_ids
                        ),
                    ]
                    if str(name).strip()
                },
                query_parameters=self._project.get("query_parameters", []),
                query_functions=self._project.get("query_functions", []),
                new_source_candidate=self._new_power_query_source_candidate,
                edit_source_candidate=self._edit_power_query_source_candidate,
                new_folder_source_candidate=self._new_power_query_folder_candidate,
                new_sql_server_source_candidate=self._new_power_query_sql_server_candidate,
                new_odata_source_candidate=self._new_power_query_odata_candidate,
                new_web_source_candidate=self._new_power_query_web_candidate,
                refresh_candidate=self._refresh_transform_query_preview,
            )
        except (OSError, QueryError, ValueError) as exc:
            self._set_status(f"Could not open Transform data: {exc}")
            QMessageBox.critical(None, "Could not transform data", str(exc))
            return False
        if open_advanced_editor:
            QTimer.singleShot(0, dialog._open_advanced_editor)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        accepted_queries = dialog.accepted_queries
        accepted_parameters = dialog.accepted_parameters
        accepted_functions = dialog.accepted_functions
        deleted_query_ids = dialog.deleted_query_ids
        if accepted_queries is not None and (
            str(source["id"]) in accepted_queries or deleted_query_ids
        ):
            return self._commit_transform_session(
                accepted_queries,
                deleted_query_ids=deleted_query_ids,
                query_parameters=accepted_parameters,
                query_functions=accepted_functions,
            )
        if dialog.candidate is None:
            return False
        return self._commit_transform_steps(
            source["id"], dialog.steps or [], dialog.candidate,
            previewed_source=active_raw_candidate,
        )

    @Slot(result=bool)
    def power_query_m_editor_dialog(self) -> bool:
        if not self.sourceLoaded or self._active_source_id is None:
            self._set_status("Load a table before opening the Power Query M editor.")
            return False
        source = next(
            (item for item in self._project["data_sources"]
             if item.get("id") == self._active_source_id),
            None,
        )
        if source is None:
            self._set_status("The active data source record is unavailable.")
            return False
        if (
            source.get("kind") == "query"
            and source.get("query_definition", {}).get("operation") == "append"
        ):
            # Append's M source is a Table.Combine over query references. Open
            # the full query session so Advanced Editor can preview those
            # staged parents and Close & Apply can commit the result safely.
            return self.transform_data_dialog(open_advanced_editor=True)
        try:
            raw_candidate = self._raw_candidate_for_source(source)
            steps = validate_steps(source.get("transform_steps", []))
            source_column_types = (
                self._query_input_column_types(
                    source, self._project, candidate=raw_candidate
                )
                if source.get("kind") == "query"
                else {}
            )
            if not source_column_types:
                source_column_types = infer_column_types(
                    raw_candidate.headers, raw_candidate.rows
                )
            current_parameters = parameter_values(
                self._project.get("query_parameters", []),
                self._project.get("query_functions", []),
            )
            issues = m_compatibility_issues(
                steps,
                parameter_names=set(current_parameters),
                query_functions=self._project.get("query_functions", []),
                initial_column_types=source_column_types,
            )
            if issues:
                details = "; ".join(
                    f"Step {issue['step']} ({issue['operation']}): {issue['message']}"
                    for issue in issues
                )
                raise ValueError(
                    "Advanced Editor cannot represent every current step in its local M subset. "
                    "Edit the steps in Transform Data first. " + details
                )
            dialog = PowerQueryMEditorDialog(
                raw_candidate,
                steps,
                self._active_model_table_name(),
                initial_script=source.get("m_script"),
                parameters=current_parameters,
                query_functions=self._project.get("query_functions", []),
                source_column_types=source_column_types,
            )
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not open Power Query M editor: {exc}")
            QMessageBox.critical(None, "Could not open Power Query M editor", str(exc))
            return False
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.candidate is None:
            return False
        return self._commit_transform_steps(
            source["id"], dialog.steps or [], dialog.candidate,
            previewed_source=raw_candidate,
            m_script=dialog.script,
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

    @Slot(str, result=bool)
    def editMeasure(self, measure_name: str) -> bool:  # noqa: N802
        """Open the DAX editor with an existing measure's saved definition."""
        if not self.sourceLoaded:
            self._set_status("Import a table before editing a measure.")
            return False
        measures = self._project.get("model", {}).get("measures", [])
        measure = next((
            item for item in measures
            if str(item.get("name", "")).casefold() == measure_name.casefold()
        ), None)
        if measure is None:
            self._set_status(f"Measure {measure_name!r} no longer exists.")
            return False
        dialog = MeasureDialog(
            list(self._headers),
            [str(item["name"]) for item in measures],
            field_references=self._dax_field_references(),
            measure_references=[
                str(item["name"]) for item in measures
                if str(item["name"]).casefold() != measure_name.casefold()
            ],
            preview_callback=lambda name, expression: self._preview_measure_expression(
                name, expression, editing_name=measure_name
            ),
            initial_measure={
                "name": str(measure["name"]),
                "expression": str(measure["expression"]),
                "description": str(measure.get("description", "")),
                "display_folder": str(measure.get("display_folder", "")),
                "is_hidden": bool(measure.get("is_hidden", False)),
            },
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.measure is None:
            return False
        return self.update_measure(
            str(measure["name"]),
            dialog.measure["name"],
            dialog.measure["expression"],
            description=dialog.measure.get("description", ""),
            display_folder=dialog.measure.get("display_folder", ""),
            is_hidden=dialog.measure.get("is_hidden", False),
        )

    @Slot(str, result=bool)
    def deleteMeasure(self, measure_name: str) -> bool:  # noqa: N802
        """Confirm removal of a saved measure, then validate dependent formulas."""
        answer = QMessageBox.question(
            None,
            "Delete measure",
            f"Delete the measure {measure_name!r}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        return self.remove_measure(measure_name)

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
                raw_candidate, source.get("transform_steps", []),
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
            persisted_types = next_table.get("column_types", {})
            initial_types = (
                dict(persisted_types)
                if isinstance(persisted_types, dict) and persisted_types
                else infer_column_types(raw_candidate.headers, raw_candidate.rows)
            )
            base_types = column_types_after_steps(
                raw_candidate.headers,
                source.get("transform_steps", []),
                initial_types=initial_types,
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
            field_references=self._dax_field_references(),
            measure_references=[str(item["name"]) for item in measures],
            preview_callback=self._preview_measure_expression,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.measure is None:
            return False
        return self.create_measure(
            dialog.measure["name"],
            dialog.measure["expression"],
            description=dialog.measure.get("description", ""),
            display_folder=dialog.measure.get("display_folder", ""),
            is_hidden=dialog.measure.get("is_hidden", False),
        )

    def _dax_field_references(self) -> list[tuple[str, str]]:
        """Return qualified references for fields in loaded model tables."""
        references: list[tuple[str, str]] = []
        for table in self._table_catalog:
            if not (table.get("loaded") and table.get("loadEnabled")):
                continue
            table_name = str(table.get("name", ""))
            if not table_name:
                continue
            escaped_table = table_name.replace("'", "''")
            display_name = str(table.get("displayName", table_name))
            for raw_column in table.get("headers", []):
                column = str(raw_column)
                # The current DAX tokenizer does not yet accept escaped closing
                # brackets in column identifiers; hide references it cannot bind.
                if not column or "]" in column or "\n" in column or "\r" in column:
                    continue
                references.append((
                    f"{display_name}[{column}]",
                    f"'{escaped_table}'[{column}]",
                ))
        return references

    def _preview_measure_expression(
        self,
        name: str,
        expression: str,
        *,
        editing_name: str | None = None,
    ) -> str:
        """Validate and evaluate a draft measure without changing project state."""
        measure = normalize_measure(name, expression)
        current = list(self._project.get("model", {}).get("measures", []))
        if editing_name is None:
            if any(
                str(item.get("name", "")).casefold() == measure["name"].casefold()
                for item in current
            ):
                raise MeasureError(f"A measure named {measure['name']!r} already exists.")
            candidate_measures = [*current, measure]
            evaluate_names = [measure["name"]]
        else:
            existing_index = next((
                index for index, item in enumerate(current)
                if str(item.get("name", "")).casefold() == editing_name.casefold()
            ), None)
            if existing_index is None:
                raise MeasureError(f"Measure {editing_name!r} no longer exists.")
            if any(
                index != existing_index
                and str(item.get("name", "")).casefold() == measure["name"].casefold()
                for index, item in enumerate(current)
            ):
                raise MeasureError(f"A measure named {measure['name']!r} already exists.")
            candidate_measures = list(current)
            candidate_measures[existing_index] = measure
            evaluate_names = None

        previous_region_column = self._region_column
        previous_filter_context_error = self._filter_context_error
        previous_filter_context_cache = self._report_filter_context_cache
        # Context construction maintains a report cache and compatibility
        # properties for normal rendering. A draft preview must leave those
        # visible controller values exactly as it found them.
        self._report_filter_context_cache = dict(previous_filter_context_cache)
        try:
            filtered_rows, table_context, filter_table_ids = self._report_filter_context()
            active_table_id = self._active_model_table_id()
            values = evaluate_measures(
                candidate_measures,
                filtered_rows.get(active_table_id, list(self._rows)),
                self._headers,
                self._active_model_table_name(),
                measure_names=evaluate_names,
                table_context=table_context,
                relationships=self._project.get("model", {}).get("relationships", []),
                filter_table_ids=filter_table_ids,
                active_table_id=active_table_id or None,
            )
        finally:
            self._report_filter_context_cache = previous_filter_context_cache
            self._region_column = previous_region_column
            self._filter_context_error = previous_filter_context_error
        value = values.get(measure["name"])
        if value is None:
            return "—"
        return _format_report_number(value)

    def create_measure(
        self,
        name: str,
        expression: str,
        *,
        description: str = "",
        display_folder: str = "",
        is_hidden: bool = False,
    ) -> bool:
        """Validate, evaluate, then transactionally add a local DAX measure."""
        if not self.sourceLoaded:
            self._set_status("Import a table before creating a measure.")
            return False
        try:
            measure = normalize_measure(
                name, expression, description=description,
                display_folder=display_folder, is_hidden=is_hidden,
            )
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

    def update_measure(
        self,
        existing_name: str,
        name: str,
        expression: str,
        *,
        description: str | None = None,
        display_folder: str | None = None,
        is_hidden: bool | None = None,
    ) -> bool:
        """Validate and transactionally replace one saved local DAX measure."""
        if not self.sourceLoaded:
            self._set_status("Import a table before editing a measure.")
            return False
        try:
            current = list(self._project.get("model", {}).get("measures", []))
            index = next((
                i for i, item in enumerate(current)
                if str(item["name"]).casefold() == existing_name.casefold()
            ), None)
            if index is None:
                raise MeasureError(f"Measure {existing_name!r} no longer exists.")
            measure = normalize_measure(
                name,
                expression,
                description=(
                    current[index].get("description", "")
                    if description is None else description
                ),
                display_folder=(
                    current[index].get("display_folder", "")
                    if display_folder is None else display_folder
                ),
                is_hidden=(
                    current[index].get("is_hidden", False)
                    if is_hidden is None else is_hidden
                ),
            )
            if any(
                i != index and item["name"].casefold() == measure["name"].casefold()
                for i, item in enumerate(current)
            ):
                raise MeasureError(f"A measure named {measure['name']!r} already exists.")
            candidate_measures = list(current)
            candidate_measures[index] = measure
            filtered_rows_by_table, measure_table_context, filter_table_ids = (
                self._report_filter_context()
            )
            active_table_id = self._active_model_table_id()
            filtered_rows = filtered_rows_by_table.get(active_table_id, list(self._rows))
            # Evaluate all measures so a rename cannot silently break dependents.
            evaluate_measures(
                candidate_measures,
                filtered_rows,
                self._headers,
                self._active_model_table_name(),
                table_context=measure_table_context,
                relationships=self._project.get("model", {}).get("relationships", []),
                filter_table_ids=filter_table_ids,
                active_table_id=active_table_id or None,
            )
            next_project = deepcopy(self._project)
            next_project.setdefault("model", {})["measures"] = candidate_measures
            if measure["name"] != existing_name:
                old_binding = _visual_measure_binding(existing_name)
                new_binding = _visual_measure_binding(measure["name"])
                for page in next_project.get("report", {}).get("pages", []):
                    for visual in page.get("visuals", []):
                        fields = visual.get("fields", {})
                        for well_fields in fields.values():
                            if not isinstance(well_fields, list):
                                continue
                            well_fields[:] = [
                                new_binding if str(item).casefold() == old_binding.casefold()
                                else item
                                for item in well_fields
                            ]
                        visual.get("field_aggregations", {}).pop(old_binding, None)
            next_project = validate_project(next_project)
        except (MeasureError, ProjectFileError, StopIteration, TypeError, ValueError) as exc:
            self._set_status(f"Could not update measure: {exc}")
            return False

        self._project = next_project
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        value = self._measure_values.get(measure["name"], "—")
        self._set_status(f"Updated measure {measure['name']} = {value}")
        return True

    def remove_measure(self, name: str) -> bool:
        """Remove one measure only when the remaining model still evaluates."""
        if not self.sourceLoaded:
            self._set_status("Import a table before removing a measure.")
            return False
        binding = _visual_measure_binding(name).casefold()
        visual_uses = [
            str(visual.get("title", "Untitled"))
            for page in self._project.get("report", {}).get("pages", [])
            for visual in page.get("visuals", [])
            for bindings in visual.get("fields", {}).values()
            if isinstance(bindings, list)
            and any(str(item).casefold() == binding for item in bindings)
        ]
        if visual_uses:
            self._set_status(
                f"Remove {name!r} from visual {visual_uses[0]!r} before deleting the measure."
            )
            return False
        try:
            current = list(self._project.get("model", {}).get("measures", []))
            retained = [item for item in current if item["name"].casefold() != name.casefold()]
            if len(retained) == len(current):
                self._set_status(f"Measure {name!r} no longer exists.")
                return False
            filtered_rows_by_table, measure_table_context, filter_table_ids = (
                self._report_filter_context()
            )
            active_table_id = self._active_model_table_id()
            filtered_rows = filtered_rows_by_table.get(active_table_id, list(self._rows))
            evaluate_measures(
                retained,
                filtered_rows,
                self._headers,
                self._active_model_table_name(),
                table_context=measure_table_context,
                relationships=self._project.get("model", {}).get("relationships", []),
                filter_table_ids=filter_table_ids,
                active_table_id=active_table_id or None,
            )
            next_project = deepcopy(self._project)
            next_project.setdefault("model", {})["measures"] = retained
            next_project = validate_project(next_project)
        except (MeasureError, ProjectFileError, StopIteration, TypeError, ValueError) as exc:
            self._set_status(f"Could not delete measure: {exc}")
            return False

        self._project = next_project
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Deleted measure {name}")
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

    @classmethod
    def _query_input_column_types(
        cls,
        source: dict[str, Any],
        project: dict[str, Any],
        *,
        candidate: ImportCandidate | None = None,
        dependency_types: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, str]:
        """Return inherited or reconciled types before a saved query's steps."""
        definition = source.get("query_definition", {})
        dependencies = definition.get("source_ids", [])
        operation = definition.get("operation")
        if operation not in {"reference", "append", "merge"}:
            return {}

        tables_by_source = {
            str(table.get("source_id") or table.get("id", "")): table
            for table in project.get("model", {}).get("tables", [])
        }

        def source_types(source_id: str) -> dict[str, str]:
            supplied = (dependency_types or {}).get(source_id)
            table = tables_by_source.get(source_id)
            calculated = {
                str(item.get("name", ""))
                for item in (table or {}).get("calculated_columns", [])
            }
            if supplied:
                return {
                    str(name): str(value)
                    for name, value in supplied.items()
                    if str(name) not in calculated
                }
            if table is None:
                return {}
            return {
                str(name): str(value)
                for name, value in table.get("column_types", {}).items()
                if str(name) not in calculated
            }

        if operation == "reference" and len(dependencies) == 1:
            return source_types(str(dependencies[0]))
        if len(dependencies) != 2:
            return {}
        left_id, right_id = (str(item) for item in dependencies)
        left_types = source_types(left_id)
        right_types = source_types(right_id)
        if operation == "append":
            headers = (
                list(candidate.headers)
                if candidate is not None
                else list(left_types)
            )
            return {
                header: (
                    left_types.get(header, "text")
                    if left_types.get(header, "text") == right_types.get(header, "text")
                    else "text"
                )
                for header in headers
            }
        if operation == "merge" and candidate is not None:
            column_sources = candidate.options.get("column_sources", {})
            if isinstance(column_sources, dict):
                result: dict[str, str] = {}
                for header in candidate.headers:
                    origin = column_sources.get(header, {})
                    if not isinstance(origin, dict):
                        result[header] = "text"
                    elif origin.get("side") == "right":
                        result[header] = right_types.get(
                            str(origin.get("column", "")), "text"
                        )
                    else:
                        result[header] = left_types.get(
                            str(origin.get("column", "")), "text"
                        )
                return result
        return {}

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

    
    @Slot(str)
    def set_view_as_role(self, role_name: str) -> None:
        """Keep legacy callers from mistaking role preview for enforced RLS."""
        self._set_status(
            "Role previews and row-level security are unavailable in this release."
        )

    def _report_filter_context(
        self,
        visual_name: str | None = None,
        *,
        include_highlights: bool = False,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], set[str]]:
        """Build page context plus optional filters for one report visual."""
        cache_key = (visual_name, include_highlights)
        cached = self._report_filter_context_cache.get(cache_key)
        if cached is not None:
            rows_by_id, context, filter_table_ids, error = cached
            self._filter_context_error = error
            return rows_by_id, context, filter_table_ids

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

        def visual_category_binding(source_visual: dict[str, Any]) -> tuple[str, str] | None:
            fields = source_visual.get("fields", {})
            preferred_table_id = str(
                source_visual.get("table_id") or self._active_model_table_id()
            )
            if source_visual.get("type") == "table":
                table = contexts_by_id.get(preferred_table_id)
                if table is None:
                    return None
                table_fields = fields.get("Fields", [])
                if not isinstance(table_fields, list):
                    return None
                for binding in table_fields:
                    if isinstance(binding, dict):
                        column = str(binding.get("column", ""))
                    elif isinstance(binding, (list, tuple)):
                        if len(binding) >= 2:
                            table_id, column = str(binding[0]), str(binding[1])
                            candidate_table = contexts_by_id.get(table_id)
                            if candidate_table is not None and column in candidate_table["headers"]:
                                return table_id, column
                            continue
                        column = str(binding[0]) if binding else ""
                    else:
                        column = str(binding)
                    if _visual_measure_name(column) is not None:
                        continue
                    if column in table["headers"]:
                        return preferred_table_id, column
                return None
            if source_visual.get("type") == "scatter":
                well_order = ("Details", "Legend", "X-axis")
            elif source_visual.get("type") == "kpi":
                well_order = ("Trend axis",)
            elif source_visual.get("type") == "map":
                well_order = ("Location",)
            else:
                well_order = ("Rows", "Fields", "Field", "X-axis", "Category")
            for well_name in well_order:
                well_fields = fields.get(well_name, [])
                if not isinstance(well_fields, list) or not well_fields:
                    continue
                if len(well_fields) >= 2:
                    table_id, column = str(well_fields[0]), str(well_fields[1])
                    table = contexts_by_id.get(table_id)
                    if table is not None and column in table["headers"]:
                        return table_id, column
                binding = well_fields[0]
                if isinstance(binding, dict):
                    table_id = str(binding.get("table_id", preferred_table_id))
                    column = str(binding.get("column", ""))
                    table = contexts_by_id.get(table_id)
                    if table is not None and column in table["headers"]:
                        return table_id, column
                    continue
                if isinstance(binding, (list, tuple)):
                    if len(binding) >= 2:
                        table_id, column = str(binding[0]), str(binding[1])
                        table = contexts_by_id.get(table_id)
                        if table is not None and column in table["headers"]:
                            return table_id, column
                    if not binding:
                        continue
                    binding = binding[0]
                if not isinstance(binding, str):
                    continue
                candidates = [
                    (table_id, table) for table_id, table in contexts_by_id.items()
                    if binding in table["headers"]
                ]
                if preferred_table_id in contexts_by_id:
                    preferred = contexts_by_id[preferred_table_id]
                    if binding in preferred["headers"]:
                        return preferred_table_id, binding
                if len(candidates) == 1:
                    return candidates[0][0], binding
                active_table_id = self._active_model_table_id()
                if (
                    active_table_id in contexts_by_id
                    and binding in contexts_by_id[active_table_id]["headers"]
                ):
                    return active_table_id, binding
            return None

        for source_visual_title, selected_values in self._cross_filters.items():
            if source_visual_title == visual_name or not isinstance(selected_values, list):
                continue
            source_visual = next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == source_visual_title
            ), None)
            if source_visual is None or not selected_values:
                continue
            target_visual = next((
                item for item in (page.get("visuals", []) if page else [])
                if isinstance(item, dict) and item.get("title") == visual_name
            ), None)
            if target_visual is not None:
                mode = self._visual_interaction_mode(source_visual, target_visual)
                if mode == "none" or (mode == "highlight" and not include_highlights):
                    continue
            else:
                target_modes = [
                    self._visual_interaction_mode(source_visual, target)
                    for target in (page.get("visuals", []) if page else [])
                    if isinstance(target, dict) and target is not source_visual
                ]
                if include_highlights:
                    if "highlight" not in target_modes and "filter" not in target_modes:
                        continue
                elif "filter" not in target_modes:
                    continue
            binding = visual_category_binding(source_visual)
            month_bucket = False
            if binding is None:
                active_table_id = self._active_model_table_id()
                active_table = contexts_by_id.get(active_table_id)
                if active_table is not None:
                    if source_visual_title == "Region revenue":
                        column = _report_field(active_table["headers"], "region")
                    elif source_visual_title == "Monthly revenue":
                        column = _report_field(active_table["headers"], "date")
                        month_bucket = column is not None
                    else:
                        column = None
                    if column:
                        binding = (active_table_id, column)
            if binding is None:
                continue
            table_id, column = binding
            if month_bucket:
                cross_filter = {
                    "clauses": [
                        {"operator": "report_month", "value": str(value)}
                        for value in selected_values
                    ],
                    "logic": "or",
                }
            else:
                cross_filter = {
                    "clauses": [{
                        "operator": "is_any_of",
                        "values": [str(value) for value in selected_values],
                    }],
                    "logic": "and",
                }
            conditions[table_id].append((column, cross_filter))

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
            # Do NOT return early entirely! Cross-filters still need to apply.

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
            if self._cross_filters:
                rows_by_id = {table_id: [] for table_id in contexts_by_id}
                source_visual = next((
                    item for item in (page.get("visuals", []) if page else [])
                    if isinstance(item, dict)
                    and item.get("title") == visual_name
                    and visual_name in self._cross_filters
                ), None)
                if source_visual is not None:
                    binding = visual_category_binding(source_visual)
                    source_table_id = (
                        binding[0] if binding
                        else str(source_visual.get("table_id") or active_table_id)
                    )
                    if source_table_id in contexts_by_id:
                        rows_by_id[source_table_id] = explicit_rows.get(
                            source_table_id,
                            list(contexts_by_id[source_table_id]["rows"]),
                        )
            else:
                rows_by_id = {
                    table_id: explicit_rows.get(table_id, list(table["rows"]))
                    for table_id, table in contexts_by_id.items()
                }
            
        result = (rows_by_id, context, filter_table_ids)
        self._report_filter_context_cache[cache_key] = (
            *result,
            self._filter_context_error,
        )
        return result

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

    def _session_raw_candidate_for_source(
        self, source: dict[str, Any]
    ) -> ImportCandidate:
        """Refresh local sources, while keeping inactive remote connectors cache-only."""
        source_id = str(source.get("id", ""))
        if source_id == self._active_source_id or source.get("kind") == "query":
            return self._raw_candidate_for_source(source)
        if source.get("kind") in {"sql_server", "odata", "web"}:
            cached = self._raw_candidates.get(source_id)
            if cached is not None:
                return cached
            raise ValueError(
                "This connector has no cached source preview. Load or refresh it before editing its query."
            )
        # Local paths are inexpensive and side-effect free to read. Refresh their
        # previews when navigating so edits never apply to an obsolete file snapshot.
        return self._raw_candidate_for_source(source)

    def _refresh_transform_query_preview(
        self,
        target_id: str,
        session_queries: dict[str, dict[str, Any]] | None = None,
        session_parameter_values: dict[str, Any] | None = None,
    ) -> tuple[
        ImportCandidate,
        dict[str, str],
        dict[str, tuple[
            ImportCandidate,
            ImportCandidate,
            dict[str, str],
            dict[str, str],
        ]],
    ]:
        """Reread a query's dependency sources without committing project changes."""
        session_queries = session_queries or {}
        sources = deepcopy(self._project.get("data_sources", []))
        sources_by_id = {str(source.get("id", "")): source for source in sources}
        for source_id, query_state in session_queries.items():
            source = sources_by_id.get(str(source_id))
            if source is None:
                if query_state.get("is_new_source"):
                    staged_source = query_state.get("source_record")
                    if not isinstance(staged_source, dict):
                        raise QueryError("The staged local source details are unavailable.")
                    source = deepcopy(staged_source)
                    source["transform_steps"] = deepcopy(
                        query_state.get("steps", [])
                    )
                    sources.append(source)
                    sources_by_id[str(source_id)] = source
                    continue
                if not query_state.get("is_new_query"):
                    continue
                source = {
                    "id": str(source_id),
                    "name": str(query_state.get("name", "")),
                    "kind": "query",
                    "query_definition": deepcopy(
                        query_state.get("query_definition", {})
                    ),
                    "transform_steps": deepcopy(query_state.get("steps", [])),
                    "include_in_report_refresh": query_state.get(
                        "include_in_report_refresh", True
                    ),
                }
                sources.append(source)
                sources_by_id[str(source_id)] = source
                continue
            if source.get("kind") == "query":
                source["query_definition"] = deepcopy(
                    query_state.get("query_definition", source.get("query_definition", {}))
                )
                source["transform_steps"] = deepcopy(
                    query_state.get("steps", source.get("transform_steps", []))
                )
                source["include_in_report_refresh"] = query_state.get(
                    "include_in_report_refresh",
                    source.get("include_in_report_refresh", True),
                )
            elif query_state.get("is_source_settings_changed"):
                staged_source = query_state.get("source_record")
                if (
                    not isinstance(staged_source, dict)
                    or str(staged_source.get("id", "")) != str(source_id)
                    or staged_source.get("kind") != source.get("kind")
                    or source.get("kind") not in {
                        "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
                        "sql_server", "odata", "web",
                    }
                    or not isinstance(staged_source.get("parser_options"), dict)
                ):
                    raise QueryError("The staged source settings do not match the existing source.")
                if source.get("kind") in {"sql_server", "odata", "web"}:
                    connection = staged_source.get("connection")
                    if not isinstance(connection, dict):
                        raise QueryError("The staged remote connection settings are invalid.")
                    source["connection"] = deepcopy(connection)
                    staged_password = staged_source.get("_staged_password")
                    if isinstance(staged_password, str) and staged_password:
                        source["_staged_password"] = staged_password
                    else:
                        source.pop("_staged_password", None)
                else:
                    source["path"] = str(staged_source.get("path", ""))
                source["parser_options"] = deepcopy(staged_source["parser_options"])
        target = sources_by_id.get(str(target_id))
        if target is None:
            raise QueryError("The selected source is no longer available.")

        session_functions = getattr(
            session_parameter_values,
            "query_functions",
            self._project.get("query_functions", []),
        )
        parameters = parameter_values(
            self._project.get("query_parameters", []), session_functions
        )
        if session_parameter_values is not None:
            # Keep unsaved typed parameter values while retaining the staged
            # function registry carried by QueryEvaluationContext.
            parameters.update(session_parameter_values)
        if not self._source_refresh_included(target):
            session_state = session_queries.get(str(target_id), {})
            candidate = session_state.get("source_candidate")
            if not isinstance(candidate, ImportCandidate):
                candidate = self._raw_candidates.get(str(target_id))
            if candidate is None:
                candidate = self._query_candidate(
                    target, self._loaded_candidates, project=self._project
                )
            if target.get("query_definition", {}).get("operation") == "reference":
                source_types = dict(session_state.get("source_column_types", {}))
                if not source_types:
                    source_types = self._query_input_column_types(target, self._project)
            else:
                source_types = dict(session_state.get("source_column_types", {}))
                if not source_types:
                    source_types = infer_column_types(candidate.headers, candidate.rows)
            return candidate, source_types, {}

        dependency_ids: set[str] = set()

        def include_dependencies(source_id: str) -> None:
            if source_id in dependency_ids:
                return
            source = sources_by_id.get(source_id)
            if source is None:
                raise QueryError(f"Query source {source_id!r} is not currently available.")
            dependency_ids.add(source_id)
            if (
                source.get("kind") == "query"
                and self._source_refresh_included(source)
            ):
                for dependency_id in source.get("query_definition", {}).get("source_ids", []):
                    include_dependencies(str(dependency_id))

        is_root_target = target.get("kind") != "query"
        if is_root_target:
            dependency_ids.add(str(target_id))
            added = True
            while added:
                added = False
                for source in sources:
                    source_id = str(source.get("id", ""))
                    if source_id in dependency_ids or source.get("kind") != "query":
                        continue
                    parents = {
                        str(item)
                        for item in source.get("query_definition", {}).get("source_ids", [])
                    }
                    if parents & dependency_ids:
                        dependency_ids.add(source_id)
                        added = True
        else:
            for dependency_id in target.get("query_definition", {}).get("source_ids", []):
                include_dependencies(str(dependency_id))

        refreshed_outputs: dict[str, ImportCandidate] = (
            dict(self._loaded_candidates) if is_root_target else {}
        )
        refreshed_types: dict[str, dict[str, str]] = {}
        refreshed_session_queries: dict[str, tuple[
            ImportCandidate,
            ImportCandidate,
            dict[str, str],
            dict[str, str],
        ]] = {}
        for source in self._source_dependency_order(sources):
            source_id = str(source.get("id", ""))
            if source_id not in dependency_ids:
                continue
            if source.get("kind") == "query" and not self._source_refresh_included(source):
                state = session_queries.get(source_id, {})
                raw_cached = state.get("source_candidate")
                if not isinstance(raw_cached, ImportCandidate):
                    raw_cached = self._raw_candidates.get(source_id)
                cached = self._loaded_candidates.get(source_id)
                if cached is None:
                    cached = state.get("preview_candidate")
                if cached is None:
                    raise QueryError(
                        f"Cannot refresh this preview because dependent query "
                        f"{source.get('name', source_id)!r} is excluded from report refresh "
                        "and has no cached result."
                    )
                refreshed_outputs[source_id] = cached
                initial_types = dict(state.get("source_column_types", {}))
                if not initial_types and isinstance(raw_cached, ImportCandidate):
                    initial_types = infer_column_types(
                        raw_cached.headers, raw_cached.rows
                    )
                steps = validate_steps(
                    state.get("steps", source.get("transform_steps", []))
                )
                if isinstance(raw_cached, ImportCandidate):
                    preview = apply_transformations(
                        raw_cached, steps, parameters=parameters
                    )
                    result_types = column_types_after_steps(
                        raw_cached.headers,
                        steps,
                        output_headers=preview.headers,
                        initial_types=initial_types,
                    )
                    cached_output, _calculated_types = self._apply_calculated_columns(
                        source_id,
                        preview,
                        project=self._project,
                        column_types=result_types,
                    )
                    # An excluded query keeps its cached source snapshot, but
                    # explicit session edits (including changed parameter values)
                    # still need the same transformed result in both the parent
                    # preview and any dependent query preview.
                    refreshed_outputs[source_id] = cached_output
                    refreshed_session_queries[source_id] = (
                        raw_cached, preview, initial_types, result_types
                    )
                else:
                    refreshed_outputs[source_id] = cached
                table = self._model_table_for_source(self._project, source_id) or {}
                calculated = {
                    str(item.get("name", ""))
                    for item in table.get("calculated_columns", [])
                }
                refreshed_types[source_id] = (
                    dict(result_types)
                    if isinstance(raw_cached, ImportCandidate)
                    else {
                        str(name): str(type_name)
                        for name, type_name in table.get("column_types", {}).items()
                        if name not in calculated
                    }
                )
                continue

            if source.get("kind") == "query":
                raw = self._query_candidate(
                    source, refreshed_outputs, project=self._project
                )
            else:
                raw = self._raw_candidate_for_source(source)
            source_state = session_queries.get(source_id, {})
            steps = validate_steps(
                source_state.get("steps", source.get("transform_steps", []))
            )
            transformed = apply_transformations(
                raw, steps, parameters=parameters
            )
            definition = source.get("query_definition", {})
            dependencies = [
                str(item) for item in definition.get("source_ids", [])
            ]
            if definition.get("operation") == "reference" and dependencies:
                source_types = dict(refreshed_types.get(dependencies[0], {}))
                if not source_types:
                    source_types = self._query_input_column_types(
                        source,
                        self._project,
                        candidate=raw,
                        dependency_types=refreshed_types,
                    )
            elif definition.get("operation") in {"append", "merge"}:
                source_types = self._query_input_column_types(
                    source,
                    self._project,
                    candidate=raw,
                    dependency_types=refreshed_types,
                )
                if not source_types:
                    source_types = infer_column_types(raw.headers, raw.rows)
            else:
                source_types = infer_column_types(raw.headers, raw.rows)
            type_map = column_types_after_steps(
                raw.headers,
                steps,
                output_headers=transformed.headers,
                initial_types=source_types,
            )
            refreshed_session_queries[source_id] = (
                raw, transformed, source_types, type_map
            )
            output, _calculated_types = self._apply_calculated_columns(
                source_id,
                transformed,
                project=self._project,
                column_types=type_map,
            )
            refreshed_outputs[source_id] = output
            refreshed_types[source_id] = type_map

        if is_root_target:
            refreshed_target = refreshed_session_queries.get(str(target_id))
            if refreshed_target is None:
                raise QueryError("The edited file source could not be refreshed.")
            raw_target = refreshed_target[0]
            source_types = refreshed_target[2]
        else:
            raw_target = self._query_candidate(
                target, refreshed_outputs, project=self._project
            )
            definition = target.get("query_definition", {})
            dependencies = [str(item) for item in definition.get("source_ids", [])]
            if definition.get("operation") == "reference" and dependencies:
                source_types = dict(refreshed_types.get(dependencies[0], {}))
                if not source_types:
                    source_types = self._query_input_column_types(
                        target,
                        self._project,
                        candidate=raw_target,
                        dependency_types=refreshed_types,
                    )
            elif definition.get("operation") in {"append", "merge"}:
                source_types = self._query_input_column_types(
                    target,
                    self._project,
                    candidate=raw_target,
                    dependency_types=refreshed_types,
                )
                if not source_types:
                    source_types = infer_column_types(raw_target.headers, raw_target.rows)
            else:
                source_types = infer_column_types(raw_target.headers, raw_target.rows)
        return raw_target, source_types, refreshed_session_queries

    def _sql_server_candidate_for_source(self, source: dict[str, Any]) -> ImportCandidate:
        connection = dict(source.get("connection", {}))
        credential_ref = str(connection.get("credential_ref", ""))
        credential_account = sql_server_credential_account(
            credential_ref, connection
        )
        staged_password = source.get("_staged_password")
        password = (
            str(staged_password)
            if isinstance(staged_password, str) and staged_password
            else self._sql_server_passwords.get(credential_account)
        )
        is_staged_password = isinstance(staged_password, str) and bool(staged_password)
        prompted = False
        if not password:
            try:
                password = get_sql_server_password(credential_ref, connection)
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
        if prompted and not is_staged_password:
            try:
                set_sql_server_password(credential_ref, password, connection)
            except CredentialStoreError as exc:
                raise SQLServerError(str(exc)) from exc
        if not is_staged_password:
            self._sql_server_passwords[credential_account] = password
        return candidate

    def _candidate_for_staged_source(
        self,
        source: dict[str, Any],
        *,
        sql_server_password: str = "",
    ) -> ImportCandidate:
        """Re-read a staged connector source without committing credentials."""
        kind = str(source.get("kind", ""))
        connection = dict(source.get("connection", {}))
        options = dict(source.get("parser_options", {}))
        if kind == "sql_server":
            if not sql_server_password:
                raise SQLServerError("A SQL Server password is required before Apply.")
            return read_sql_server_object(connection, options, sql_server_password)
        if kind == "odata":
            return read_odata_entity_set(connection, options)
        if kind == "web":
            return read_web_source(connection, options)
        raise ValueError("The staged source connector is not supported.")

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
        if operation == "reference" and len(inputs) == 1:
            candidate = inputs[0]
            source_id = str(source_ids[0])
            table = StudioController._model_table_for_source(project or {}, source_id)
            calculated_columns = {
                str(item.get("name", ""))
                for item in (table or {}).get("calculated_columns", [])
            }
            headers = [
                header for header in candidate.headers
                if header not in calculated_columns
            ]
            return ImportCandidate(
                kind="query",
                headers=headers,
                rows=[
                    {header: row.get(header, "") for header in headers}
                    for row in candidate.rows
                ],
                options={},
                notices=[],
            )
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
            query_candidate = apply_transformations(
                raw, source.get("transform_steps", []),
                parameters=parameter_values(project.get("query_parameters", []), project.get("query_functions", [])),
            )
            type_map = column_types_after_steps(
                raw.headers,
                source.get("transform_steps", []),
                output_headers=query_candidate.headers,
                initial_types=self._query_input_column_types(
                    source,
                    project,
                    candidate=raw,
                    dependency_types=type_maps,
                ),
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

    def _sqlite_binding_conflict(
        self,
        sources: list[dict[str, Any]],
        affected_source_ids: set[str],
    ) -> bool:
        """Check final SQLite bindings changed in this session for duplicates."""
        if not affected_source_ids:
            return False
        seen: dict[tuple[tuple[Any, ...], str], str] = {}
        for source in sources:
            if source.get("kind") != "sqlite":
                continue
            source_id = str(source.get("id", ""))
            options = source.get("parser_options", {})
            if not isinstance(options, dict):
                continue
            table_name = str(options.get("table_name", ""))
            if not table_name.strip():
                continue
            try:
                path = self._resolved_source_path(source)
                stat = path.stat()
                path_identity: tuple[Any, ...] = ("file", stat.st_dev, stat.st_ino)
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                try:
                    path_identity = ("path", os.path.normcase(str(self._resolved_source_path(source))))
                except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                    continue
            # SQLite folds ASCII identifier letters for object-name matching;
            # Unicode casefolding would incorrectly merge distinct names such
            # as "Straße" and "STRASSE".
            sqlite_name_key = "".join(
                chr(ord(character) + 32)
                if "A" <= character <= "Z"
                else character
                for character in table_name
            )
            key = (path_identity, sqlite_name_key)
            previous_id = seen.get(key)
            if previous_id is not None and (
                source_id in affected_source_ids
                or previous_id in affected_source_ids
            ):
                return True
            seen.setdefault(key, source_id)
        return False

    def _commit_transform_steps(
        self,
        source_id: str,
        steps: list[dict[str, str]],
        transformed: ImportCandidate,
        *,
        previewed_source: ImportCandidate | None = None,
        m_script: str | None = None,
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
            confirmed = apply_transformations(
                raw_candidate, validated_steps,
                parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
            )
            if confirmed != transformed:
                self._set_status(
                    "The transformation result no longer matches its preview. Reopen Transform data and try again."
                )
                return False
            source_column_types = (
                self._query_input_column_types(
                    source, self._project, candidate=raw_candidate
                )
                if source.get("kind") == "query"
                else {}
            )
            if not source_column_types:
                source_column_types = infer_column_types(
                    raw_candidate.headers, raw_candidate.rows
                )
            next_project = deepcopy(self._project)
            target = next(
                item for item in next_project["data_sources"]
                if item.get("id") == source_id
            )
            target["transform_steps"] = validated_steps
            table_name = self._active_model_table_name() if source_id == self._active_source_id else str(
                target.get("query_name", target.get("name", "Table"))
            )
            if isinstance(m_script, str) and m_script_matches_steps(
                m_script, table_name, validated_steps,
                parameter_names=set(parameter_values(
                    self._project.get("query_parameters", [])
                )),
                query_functions=self._project.get("query_functions", []),
                initial_column_types=source_column_types,
            ):
                target["m_script"] = m_script
            else:
                target.pop("m_script", None)
            type_map = column_types_after_steps(
                raw_candidate.headers,
                validated_steps,
                output_headers=confirmed.headers,
                initial_types=source_column_types,
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
        self._raw_candidates[source_id] = raw_candidate
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

    def _commit_transform_session(
        self,
        query_results: dict[str, dict[str, Any]],
        *,
        deleted_query_ids: set[str] | None = None,
        query_parameters: list[dict[str, str]] | None = None,
        query_functions: list[dict[str, str]] | None = None,
    ) -> bool:
        """Validate and commit edits from the multi-query Power Query session atomically."""
        deleted_query_ids = set(deleted_query_ids or set())
        session_project = deepcopy(self._project)
        original_parameters = deepcopy(
            session_project.get("query_parameters", [])
        )
        if query_parameters is not None:
            session_project["query_parameters"] = deepcopy(query_parameters)
        original_functions = deepcopy(session_project.get("query_functions", []))
        if query_functions is not None:
            session_project["query_functions"] = deepcopy(query_functions)
        parameters_changed = (
            session_project.get("query_parameters", []) != original_parameters
        )
        old_parameters = {
            item.get("name"): item
            for item in original_parameters if isinstance(item, dict)
        }
        new_parameters = {
            item.get("name"): item
            for item in session_project.get("query_parameters", [])
            if isinstance(item, dict)
        }
        changed_parameter_names = {
            name for name in old_parameters.keys() | new_parameters.keys()
            if old_parameters.get(name) != new_parameters.get(name)
        }
        old_functions = {
            item.get("name"): item
            for item in original_functions if isinstance(item, dict)
        }
        new_functions = {
            item.get("name"): item
            for item in session_project.get("query_functions", [])
            if isinstance(item, dict)
        }
        changed_function_names = {
            name for name in old_functions.keys() | new_functions.keys()
            if old_functions.get(name) != new_functions.get(name)
        }
        functions_changed = bool(changed_function_names)
        source_by_id = {
            str(source.get("id", "")): source
            for source in session_project.get("data_sources", [])
        }
        missing_deletions = deleted_query_ids - source_by_id.keys()
        if missing_deletions:
            self._set_status("A query selected for deletion no longer exists in this project.")
            return False
        deleted_sql_credentials = [
            (
                str(source.get("connection", {}).get("credential_ref", "")),
                dict(source.get("connection", {})),
            )
            for source in self._project.get("data_sources", [])
            if str(source.get("id", "")) in deleted_query_ids
            and source.get("kind") == "sql_server"
        ]
        if deleted_query_ids & query_results.keys():
            self._set_status("A query cannot be edited and deleted in the same Power Query session.")
            return False
        if deleted_query_ids and len(source_by_id) <= len(deleted_query_ids):
            self._set_status("At least one query must remain in the project.")
            return False
        source_settings_change_ids: set[str] = set()
        staged_sql_passwords: dict[str, str] = {}
        local_source_kinds = {
            "csv", "excel", "json", "xml", "parquet", "sqlite", "folder",
        }
        remote_source_kinds = {"sql_server", "odata", "web"}
        for source_id, result in query_results.items():
            if result.get("is_source_settings_changed") is not True:
                continue
            current_source = source_by_id.get(str(source_id))
            staged_source = result.get("source_record")
            candidate = result.get("source_candidate")
            if (
                current_source is None
                or not isinstance(staged_source, dict)
                or not isinstance(candidate, ImportCandidate)
                or current_source.get("kind") not in (
                    local_source_kinds | remote_source_kinds
                )
                or str(staged_source.get("id", "")) != str(source_id)
                or staged_source.get("kind") != current_source.get("kind")
                or candidate.kind != current_source.get("kind")
                or not isinstance(staged_source.get("parser_options"), dict)
            ):
                self._set_status("The staged source settings do not match the existing source.")
                return False
            stable_keys = (set(current_source) | set(staged_source)) - {
                "path", "parser_options", "connection", "_staged_password",
            }
            if any(
                current_source.get(key) != staged_source.get(key)
                for key in stable_keys
            ):
                self._set_status("Source settings cannot replace the existing query definition.")
                return False
            if dict(staged_source["parser_options"]) != dict(candidate.options):
                self._set_status("The staged parser options do not match the source preview.")
                return False
            if current_source.get("kind") in local_source_kinds:
                staged_path = str(staged_source.get("path", "")).strip()
                try:
                    if not staged_path:
                        raise ValueError("Choose a valid path for this source.")
                    if current_source.get("kind") == "folder":
                        if not Path(staged_path).expanduser().resolve().is_dir():
                            raise ValueError("Choose an existing folder for this source.")
                    elif kind_for_path(Path(staged_path)) != current_source.get("kind"):
                        raise ValueError(
                            "Choose a path with the same file type as the existing source."
                        )
                except (OSError, ValueError) as exc:
                    self._set_status(f"The staged source path is invalid: {exc}")
                    return False
            else:
                staged_connection = staged_source.get("connection")
                required_key = {
                    "sql_server": "credential_ref",
                    "odata": "service_root",
                    "web": "url",
                }[str(current_source.get("kind"))]
                if (
                    not isinstance(staged_connection, dict)
                    or not str(staged_connection.get(required_key, "")).strip()
                ):
                    self._set_status("The staged remote connection settings are incomplete.")
                    return False
                if current_source.get("kind") == "sql_server":
                    old_connection = dict(current_source.get("connection", {}))
                    new_credential_ref = str(
                        staged_connection.get("credential_ref", "")
                    )
                    old_credential_ref = str(old_connection.get("credential_ref", ""))
                    staged_password = staged_source.get("_staged_password")
                    if (
                        new_credential_ref != old_credential_ref
                        and not (isinstance(staged_password, str) and staged_password)
                    ):
                        self._set_status(
                            "A changed SQL Server connection needs a password before Apply."
                        )
                        return False
                    if isinstance(staged_password, str) and staged_password:
                        staged_sql_passwords[str(source_id)] = staged_password
                    if old_credential_ref and new_credential_ref != old_credential_ref:
                        deleted_sql_credentials.append(
                            (old_credential_ref, old_connection)
                        )
                current_source["connection"] = deepcopy(staged_connection)
            if current_source.get("kind") == "sqlite":
                staged_path_resolved = Path(staged_path).expanduser().resolve()
                staged_table_name = str(candidate.options.get("table_name", ""))
                for other_id, other_source in source_by_id.items():
                    if other_id == str(source_id) or other_id in deleted_query_ids:
                        continue
                    other_record = other_source
                    other_result = query_results.get(other_id)
                    if (
                        other_result is not None
                        and other_result.get("is_source_settings_changed") is True
                        and isinstance(other_result.get("source_record"), dict)
                    ):
                        other_record = other_result["source_record"]
                    if other_record.get("kind") != "sqlite":
                        continue
                    other_options = other_record.get("parser_options", {})
                    if not isinstance(other_options, dict):
                        continue
                    other_path = str(other_record.get("path", "")).strip()
                    if not other_path:
                        continue
                    try:
                        same_path = Path(other_path).expanduser().resolve() == staged_path_resolved
                    except (OSError, RuntimeError, TypeError, ValueError):
                        continue
                    if same_path and str(other_options.get("table_name", "")) == staged_table_name:
                        self._set_status(
                            "This SQLite database table is already linked to another source in the project."
                        )
                        return False
            if current_source.get("kind") in local_source_kinds:
                current_source["path"] = str(Path(staged_path).expanduser().resolve())
            current_source["parser_options"] = deepcopy(staged_source["parser_options"])
            source_settings_change_ids.add(str(source_id))
        new_source_ids: set[str] = set()
        reserved_model_names = {
            str(table.get("name", "")).strip().casefold()
            for table in session_project.get("model", {}).get("tables", [])
            if str(table.get("source_id") or table.get("id", ""))
            not in deleted_query_ids
            if str(table.get("name", "")).strip()
        }
        reserved_model_names.update(
            str(source.get("query_name", source.get("name", ""))).strip().casefold()
            for source in session_project.get("data_sources", [])
            if str(source.get("id", "")) not in deleted_query_ids
            if str(source.get("query_name", source.get("name", ""))).strip()
        )
        for query_id, result in query_results.items():
            if query_id in source_by_id:
                if result.get("is_new_query"):
                    self._set_status("A new query ID conflicts with an existing data source.")
                    return False
                continue
            if not result.get("is_new_query"):
                self._set_status("A query was removed while the Power Query session was open.")
                return False
            query_name = str(result.get("name", "")).strip()
            is_new_source = result.get("is_new_source") is True
            is_duplicate = result.get("is_duplicate") is True
            duplicate_of_id = str(result.get("duplicate_of_id", ""))
            original_source = source_by_id.get(duplicate_of_id) if is_duplicate else None
            definition = (
                deepcopy(original_source.get("query_definition", {}))
                if original_source is not None
                else result.get("query_definition")
            )
            staged_source_record = result.get("source_record")
            valid_new_source = False
            if isinstance(staged_source_record, dict):
                staged_kind = str(staged_source_record.get("kind", ""))
                local_source = staged_kind in {
                    "csv", "excel", "json", "xml", "parquet", "sqlite", "folder"
                }
                remote_source = staged_kind in {"sql_server", "odata", "web"}
                connection = staged_source_record.get("connection", {})
                required_connection_key = {
                    "sql_server": "credential_ref",
                    "odata": "service_root",
                    "web": "url",
                }.get(staged_kind)
                valid_new_source = (
                    str(staged_source_record.get("id", "")) == query_id
                    and isinstance(staged_source_record.get("parser_options", {}), dict)
                    and (
                        (
                            local_source
                            and isinstance(staged_source_record.get("path"), str)
                            and bool(staged_source_record.get("path", "").strip())
                        )
                        or (
                            remote_source
                            and isinstance(connection, dict)
                            and bool(str(connection.get(required_connection_key, "")).strip())
                        )
                    )
                    and (
                        staged_kind != "sql_server"
                        or bool(str(staged_source_record.get("_staged_password", "")))
                    )
                )
            if (
                (not is_new_source and not isinstance(definition, dict))
                or (
                    not is_new_source
                    and not is_duplicate
                    and isinstance(definition, dict)
                    and definition.get("operation")
                    not in {"reference", "append", "merge"}
                )
                or (is_new_source and not valid_new_source)
                or (not is_new_source and is_duplicate and original_source is None)
                or not query_name
                or len(query_name) > 120
                or any(ord(char) < 32 for char in query_name)
            ):
                self._set_status("The new query definition or name is invalid.")
                return False
            if query_name.casefold() in reserved_model_names:
                self._set_status(
                    f"A model table or query named {query_name!r} already exists."
                )
                return False
            reserved_model_names.add(query_name.casefold())
            if is_new_source:
                source_record = deepcopy(staged_source_record)
                source_record["query_name"] = query_name
                source_record["transform_steps"] = []
            elif is_duplicate:
                source_record = deepcopy(original_source)
                source_record["id"] = query_id
                source_record["name"] = query_name
                source_record["query_name"] = query_name
                source_record["transform_steps"] = deepcopy(result.get("steps", []))
                source_record["step_metadata"] = deepcopy(
                    result.get("step_metadata", [])
                )
                if source_record.get("kind") == "query":
                    source_record["query_definition"] = definition
                    source_record["load_enabled"] = result.get("load_enabled", True)
                    if result.get("include_in_report_refresh", True):
                        source_record.pop("include_in_report_refresh", None)
                    else:
                        source_record["include_in_report_refresh"] = False
                else:
                    source_record.pop("query_definition", None)
                    source_record.pop("load_enabled", None)
                    source_record.pop("include_in_report_refresh", None)
            else:
                source_record = {
                    "id": query_id,
                    "name": query_name,
                    "query_name": query_name,
                    "kind": "query",
                    "query_definition": deepcopy(definition),
                    "transform_steps": [],
                    "load_enabled": result.get("load_enabled", True),
                }
                if not result.get("include_in_report_refresh", True):
                    source_record["include_in_report_refresh"] = False
            staged_password = source_record.pop("_staged_password", None)
            if isinstance(staged_password, str) and staged_password:
                if source_record.get("kind") != "sql_server":
                    self._set_status("Only SQL Server sources can stage connector credentials.")
                    return False
                staged_sql_passwords[query_id] = staged_password
            if result.get("description"):
                source_record["description"] = str(result["description"])
            else:
                source_record.pop("description", None)
            if result.get("query_group"):
                source_record["query_group"] = str(result["query_group"])
            else:
                source_record.pop("query_group", None)
            session_project["data_sources"].append(source_record)
            source_by_id[query_id] = source_record
            new_source_ids.add(query_id)
        if deleted_query_ids:
            blockers = _query_deletion_blockers(
                session_project,
                deleted_query_ids,
                active_source_id=self._active_source_id,
            )
            if blockers:
                details = "; ".join(blockers[:4])
                if len(blockers) > 4:
                    details += f"; and {len(blockers) - 4} more dependency/dependencies"
                self._set_status(
                    "Cannot delete the selected query while project objects depend on it: "
                    + details
                    + ". Remove or rebind those objects first."
                )
                return False
            session_project["data_sources"] = [
                source for source in session_project.get("data_sources", [])
                if str(source.get("id", "")) not in deleted_query_ids
            ]
            session_project["model"]["tables"] = [
                table for table in session_project.get("model", {}).get("tables", [])
                if str(table.get("id", "")) not in deleted_query_ids
                and str(table.get("source_id", "")) not in deleted_query_ids
            ]
            if session_project.get("active_source_id") in deleted_query_ids:
                surviving = self._source_dependency_order(session_project["data_sources"])
                next_active = next((
                    str(item.get("id", ""))
                    for item in surviving
                    if str(item.get("id", "")) in self._loaded_candidates
                    and self._source_load_enabled(item)
                ), None)
                if next_active is None:
                    next_active = next((
                        str(item.get("id", "")) for item in surviving
                    ), None)
                session_project["active_source_id"] = next_active
        try:
            session_project = validate_project(session_project)
        except ProjectFileError as exc:
            self._set_status(f"Could not validate the Power Query session: {exc}")
            return False
        validated_results: dict[str, tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], ImportCandidate, ImportCandidate]] = {}
        baseline_outputs = dict(self._loaded_candidates)
        raw_snapshots: dict[str, ImportCandidate] = {}
        session_type_maps: dict[str, dict[str, str]] = {}
        staged_reference_sources = {
            str(result.get("query_definition", {}).get("source_ids", [""])[0])
            for result in query_results.values()
            if result.get("is_new_query")
            and result.get("query_definition", {}).get("operation") == "reference"
            and result.get("query_definition", {}).get("source_ids")
        }
        source_settings_affected_ids = set(source_settings_change_ids)
        while True:
            affected_dependents = {
                str(source.get("id", ""))
                for source in session_project.get("data_sources", [])
                if source.get("kind") == "query"
                and any(
                    str(parent_id) in source_settings_affected_ids
                    for parent_id in source.get("query_definition", {}).get("source_ids", [])
                )
            }
            added_dependents = affected_dependents - source_settings_affected_ids
            if not added_dependents:
                break
            source_settings_affected_ids.update(added_dependents)
        function_affected_query_ids = {
            str(query_id)
            for query_id, result in query_results.items()
            if function_references(
                result.get("steps", []), session_project.get("query_functions", [])
            ) & changed_function_names
        }
        # A function edit can change an upstream result even when a saved
        # Reference Query's own steps are empty. Propagate that invalidation
        # through reference/append/merge dependencies before validating their
        # session snapshots.
        while True:
            downstream_ids = {
                str(query_id)
                for query_id, result in query_results.items()
                if any(
                    str(parent_id) in function_affected_query_ids
                    for parent_id in result.get("query_definition", {}).get(
                        "source_ids", []
                    )
                )
            }
            added_ids = downstream_ids - function_affected_query_ids
            if not added_ids:
                break
            function_affected_query_ids.update(added_ids)
        for source in self._source_dependency_order(session_project.get("data_sources", [])):
            source_id = str(source.get("id", ""))
            if source_id not in query_results:
                continue
            result = query_results[source_id]
            if source_id not in source_by_id:
                self._set_status("A query was removed while the Power Query session was open.")
                return False
            try:
                validated = validate_steps(result.get("steps", []))
            except (TransformationError, TypeError, ValueError) as exc:
                self._set_status(f"Could not validate query {source.get('name', source_id)!r}: {exc}")
                return False
            try:
                baseline_outputs.pop(source_id, None)
                frozen_query = (
                    source_id not in new_source_ids
                    and source.get("kind") == "query"
                    and not self._source_refresh_included(source)
                )
                if frozen_query:
                    raw_candidate = self._raw_candidates.get(source_id)
                    if raw_candidate is None:
                        raw_candidate = self._query_candidate(
                            source, self._loaded_candidates, project=self._project
                        )
                elif source.get("kind") == "query":
                    definition = source.get("query_definition", {})
                    operation = definition.get("operation")
                    if (
                        source_id in new_source_ids
                        and not result.get("is_duplicate")
                        and operation in {"append", "merge"}
                    ):
                        # A newly staged combine must use the selected parents'
                        # current session previews, including edits that have
                        # not yet been saved on those parents. Existing saved
                        # dependencies keep their normal refresh/cache rules.
                        combine_inputs = dict(baseline_outputs)
                        for dependency_id in definition.get("source_ids", []):
                            dependency_id = str(dependency_id)
                            dependency_result = query_results.get(dependency_id)
                            dependency_preview = (
                                dependency_result.get("candidate")
                                if dependency_result is not None
                                else None
                            )
                            if isinstance(dependency_preview, ImportCandidate):
                                combine_inputs[dependency_id] = dependency_preview
                        raw_candidate = self._query_candidate(
                            source, combine_inputs, project=session_project
                        )
                    else:
                        raw_candidate = self._query_candidate(
                            source, baseline_outputs, project=session_project
                        )
                elif source_id in new_source_ids and result.get("is_new_source"):
                    if source.get("kind") in {"sql_server", "odata", "web"}:
                        if (
                            result.get("preview_refreshed") is True
                            and isinstance(
                                result.get("source_candidate"), ImportCandidate
                            )
                        ):
                            # Apply the remote snapshot explicitly previewed in
                            # this session. Re-fetching here can invalidate an
                            # otherwise current preview for a changing endpoint.
                            raw_candidate = result["source_candidate"]
                        else:
                            raw_candidate = self._candidate_for_staged_source(
                                source,
                                sql_server_password=staged_sql_passwords.get(
                                    source_id, ""
                                ),
                            )
                    else:
                        raw_candidate = self._session_raw_candidate_for_source(source)
                elif source_id in new_source_ids:
                    duplicate_of_id = str(result.get("duplicate_of_id", ""))
                    raw_candidate = raw_snapshots.get(duplicate_of_id)
                    if raw_candidate is None:
                        raw_candidate = self._raw_candidates.get(duplicate_of_id)
                    if raw_candidate is None:
                        raise QueryError(
                            f"The source preview for duplicate query {source.get('name', source_id)!r} is unavailable."
                        )
                elif (
                    source.get("kind") in {"sql_server", "odata", "web"}
                    and result.get("preview_refreshed") is True
                    and isinstance(result.get("source_candidate"), ImportCandidate)
                ):
                    # Explicit Preview refresh captures a remote source snapshot.
                    # Reuse that snapshot through Apply instead of switching back
                    # to the inactive-connector cache and rejecting its own preview.
                    raw_candidate = result["source_candidate"]
                else:
                    raw_candidate = self._session_raw_candidate_for_source(source)
                previewed_source = result.get("source_candidate")
                previewed_result = result.get("candidate")
                is_staged_reference_or_duplicate = (
                    source_id in new_source_ids
                    and (
                        source.get("query_definition", {}).get("operation")
                        == "reference"
                        or result.get("is_duplicate") is True
                    )
                )
                is_function_dependent_reference = (
                    source.get("query_definition", {}).get("operation") == "reference"
                    and any(
                        str(parent_id) in function_affected_query_ids
                        for parent_id in source.get("query_definition", {}).get(
                            "source_ids", []
                        )
                    )
                )
                if (
                    is_function_dependent_reference
                    and isinstance(previewed_source, ImportCandidate)
                ):
                    # The session preview already contains staged parent steps
                    # and function definitions. Reuse it for this saved
                    # Reference Query so Apply persists the same rows the user
                    # just reviewed.
                    raw_candidate = previewed_source
                can_rebuild_from_staged_dependency = (
                    is_staged_reference_or_duplicate
                    or is_function_dependent_reference
                )
                if (
                    raw_candidate != previewed_source
                    and not can_rebuild_from_staged_dependency
                ):
                    self._set_status(
                        f"The source for {source.get('name', source_id)!r} changed during the Power Query session. Reopen it and preview again."
                    )
                    return False
                transformed = apply_transformations(
                    raw_candidate, validated,
                    parameters=parameter_values(session_project.get("query_parameters", []), session_project.get("query_functions", [])),
                )
                if (
                    transformed != previewed_result
                    and not can_rebuild_from_staged_dependency
                ):
                    self._set_status(
                        f"The preview for {source.get('name', source_id)!r} no longer matches its steps. Reopen it and preview again."
                    )
                    return False
                # Downstream query source candidates in the open session were
                # built from these saved upstream steps and refreshed root data.
                definition = source.get("query_definition", {})
                initial_types: dict[str, str] = {}
                if definition.get("operation") == "reference":
                    dependency_ids = definition.get("source_ids", [])
                    if dependency_ids:
                        dependency_id = str(dependency_ids[0])
                        if dependency_id in staged_reference_sources or dependency_id in new_source_ids:
                            initial_types = dict(session_type_maps.get(dependency_id, {}))
                        if not initial_types:
                            initial_types = self._query_input_column_types(
                                source, session_project
                            )
                elif definition.get("operation") in {"append", "merge"}:
                    initial_types = self._query_input_column_types(
                        source,
                        session_project,
                        candidate=raw_candidate,
                        dependency_types=session_type_maps,
                    )
                    if not initial_types:
                        initial_types = infer_column_types(
                            raw_candidate.headers, raw_candidate.rows
                        )
                else:
                    # Keep commit-time validation aligned with the types shown
                    # in the editor preview for root and combined queries.
                    initial_types = infer_column_types(
                        raw_candidate.headers, raw_candidate.rows
                    )
                result_types = column_types_after_steps(
                    raw_candidate.headers,
                    validated,
                    output_headers=transformed.headers,
                    initial_types=initial_types,
                )
                if source_id in source_settings_affected_ids:
                    old_output = self._loaded_candidates.get(source_id)
                    model_table = self._model_table_for_source(self._project, source_id)
                    calculated_names = {
                        str(item.get("name", ""))
                        for item in (model_table or {}).get("calculated_columns", [])
                    }
                    old_type_map = {
                        str(column): str(column_type)
                        for column, column_type in (model_table or {}).get(
                            "column_types", {}
                        ).items()
                        if str(column) not in calculated_names
                    }
                    old_headers = (
                        [header for header in old_output.headers if header not in calculated_names]
                        if old_output is not None else None
                    )
                    if (
                        (old_headers is not None and transformed.headers != old_headers)
                        or (model_table is not None and result_types != old_type_map)
                    ):
                        self._set_status(
                            "Source settings must preserve existing column names or data types for "
                            f"{source.get('name', source_id)!r} so model and report references remain valid."
                        )
                        return False
                session_type_maps[source_id] = result_types
                staged_output, _calculated_types = self._apply_calculated_columns(
                    source_id,
                    transformed,
                    project=session_project,
                    column_types=result_types,
                )
                existing_steps = validate_steps(source.get("transform_steps", []))
                parameter_affects_query = bool(
                    parameter_references(
                        validated,
                        function_names={
                            item["name"]
                            for item in session_project.get("query_functions", [])
                        },
                    ) & changed_parameter_names
                )
                function_affects_query = bool(
                    function_references(
                        validated, session_project.get("query_functions", [])
                    ) & changed_function_names
                )
                if (
                    frozen_query
                    and validated == existing_steps
                    and not parameter_affects_query
                    and not function_affects_query
                    and not is_function_dependent_reference
                ):
                    # An untouched excluded query remains frozen at its last
                    # evaluated output, even when an upstream source changed.
                    baseline_output = self._loaded_candidates[source_id]
                elif frozen_query:
                    # A user-edited excluded query replays from its cached raw
                    # input, but still does not re-read its external source.
                    baseline_output = staged_output
                elif source_id in staged_reference_sources or source_id in new_source_ids:
                    baseline_output = staged_output
                else:
                    baseline_steps = existing_steps
                    baseline_transformed = apply_transformations(
                        raw_candidate, baseline_steps,
                        parameters=parameter_values(session_project.get("query_parameters", []), session_project.get("query_functions", [])),
                    )
                    baseline_types = column_types_after_steps(
                        raw_candidate.headers,
                        baseline_steps,
                        output_headers=baseline_transformed.headers,
                        initial_types=initial_types,
                    )
                    baseline_output, _baseline_calculated_types = self._apply_calculated_columns(
                        source_id,
                        baseline_transformed,
                        project=session_project,
                        column_types=baseline_types,
                    )
                baseline_outputs[source_id] = baseline_output
            except (OSError, QueryError, TransformationError, TypeError, ValueError) as exc:
                self._set_status(f"Could not validate the preview for {source.get('name', source_id)!r}: {exc}")
                return False
            validated_results[source_id] = (
                source, result, validated, raw_candidate, transformed
            )
            raw_snapshots[source_id] = raw_candidate

        parameter_change_sources = {
            source_id
            for source_id, (_source, _result, steps, _raw, _transformed)
            in validated_results.items()
            if parameter_references(
                steps,
                function_names={
                    item["name"]
                    for item in session_project.get("query_functions", [])
                },
            ) & changed_parameter_names
        }
        function_change_sources = {
            source_id
            for source_id, (source, _result, steps, _raw, _transformed)
            in validated_results.items()
            if function_references(
                steps, session_project.get("query_functions", [])
            ) & changed_function_names
        }
        function_change_sources.update(
            source_id
            for source_id in function_affected_query_ids
            if source_id in validated_results
            and validated_results[source_id][0].get("query_definition", {}).get(
                "operation"
            ) == "reference"
        )

        dependencies = {
            str(source.get("id", "")): [
                str(item) for item in source.get("query_definition", {}).get("source_ids", [])
            ]
            for source in session_project.get("data_sources", [])
            if source.get("kind") == "query"
        }

        def depends_on(source_id: str, ancestor_id: str) -> bool:
            pending = list(dependencies.get(source_id, []))
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == ancestor_id:
                    return True
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(dependencies.get(current, []))
            return False

        try:
            next_project = deepcopy(session_project)
            base_candidates: dict[str, ImportCandidate] = {}
            changes: dict[str, tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = {}
            step_change_ids: set[str] = set()
            metadata_change_ids: set[str] = set()
            for source_id, (current_source, result, steps, raw_candidate, transformed) in validated_results.items():
                target = next(
                    item for item in next_project["data_sources"]
                    if item.get("id") == source_id
                )
                if current_source.get("kind") == "query":
                    load_enabled = result.get(
                        "load_enabled", current_source.get("load_enabled", True)
                    )
                    refresh_included = result.get(
                        "include_in_report_refresh",
                        current_source.get("include_in_report_refresh", True),
                    )
                    if not isinstance(load_enabled, bool):
                        raise ProjectFileError(
                            f"The load setting for {current_source.get('name', source_id)!r} must be true or false."
                        )
                    if not isinstance(refresh_included, bool):
                        raise ProjectFileError(
                            f"The refresh setting for {current_source.get('name', source_id)!r} must be true or false."
                        )
                    target["load_enabled"] = load_enabled
                    if load_enabled != self._source_load_enabled(current_source):
                        metadata_change_ids.add(source_id)
                    if refresh_included:
                        target.pop("include_in_report_refresh", None)
                    else:
                        target["include_in_report_refresh"] = False
                    if refresh_included != self._source_refresh_included(current_source):
                        metadata_change_ids.add(source_id)
                model_table = self._model_table_for_source(next_project, source_id)
                old_query_name = (
                    str(model_table.get("name", ""))
                    if model_table is not None
                    else str(current_source.get("query_name", current_source.get("name", "")))
                )
                query_name = str(result.get("name", old_query_name)).strip()
                if (
                    not query_name
                    or len(query_name) > 120
                    or any(ord(char) < 32 for char in query_name)
                ):
                    raise ProjectFileError(
                        "Query names must be 1–120 characters and contain no control characters."
                    )
                if model_table is not None and query_name != old_query_name:
                    model_name_collision = next((
                        item for item in next_project.get("model", {}).get("tables", [])
                        if item is not model_table
                        and str(item.get("name", "")).casefold() == query_name.casefold()
                    ), None)
                    unloaded_name_collision = next((
                        item for item in next_project.get("data_sources", [])
                        if item.get("id") != source_id
                        and self._model_table_for_source(
                            next_project, str(item.get("id", ""))
                        ) is None
                        and item.get("kind") == "query"
                        and str(item.get("query_name", item.get("name", ""))).casefold()
                        == query_name.casefold()
                    ), None)
                    if model_name_collision is not None or unloaded_name_collision is not None:
                        raise ProjectFileError(
                            f"A model table named {query_name!r} already exists."
                        )
                    if query_name.casefold() != old_query_name.casefold():
                        _rename_table_references_in_project(
                            next_project, old_query_name, query_name
                        )
                    model_table["name"] = query_name
                    metadata_change_ids.add(source_id)
                if target.get("query_name") != query_name:
                    metadata_change_ids.add(source_id)
                target["query_name"] = query_name
                previous_m_script = target.get("m_script")
                accepted_m_script = result.get("m_script")
                query_definition = result.get(
                    "query_definition", current_source.get("query_definition", {})
                )
                source_query_names = None
                if query_definition.get("operation") == "append":
                    def query_reference_name(parent_id: Any) -> str:
                        parent_id = str(parent_id)
                        parent_source = source_by_id.get(parent_id, {})
                        staged_parent = query_results.get(parent_id, {})
                        staged_name = str(staged_parent.get("name", "")).strip()
                        if staged_name:
                            return staged_name
                        parent_table = self._model_table_for_source(
                            session_project, parent_id
                        )
                        return str(
                            (parent_table or {}).get("name")
                            or parent_source.get("query_name")
                            or parent_source.get("name", "")
                        )

                    source_query_names = [
                        query_reference_name(parent_id)
                        for parent_id in query_definition.get("source_ids", [])
                    ]
                if (
                    isinstance(accepted_m_script, str)
                    and m_script_matches_steps(
                        accepted_m_script, query_name, steps,
                        parameter_names=set(parameter_values(
                            session_project.get("query_parameters", [])
                        )),
                        query_functions=session_project.get("query_functions", []),
                        source_query_names=source_query_names,
                        initial_column_types=result.get(
                            "source_column_types", {}
                        ),
                    )
                ):
                    target["m_script"] = accepted_m_script
                else:
                    target.pop("m_script", None)
                if target.get("m_script") != previous_m_script:
                    metadata_change_ids.add(source_id)
                description = str(
                    result.get("description", current_source.get("description", ""))
                ).strip()
                if description:
                    target["description"] = description
                else:
                    target.pop("description", None)
                if description != str(current_source.get("description", "")):
                    metadata_change_ids.add(source_id)
                target["transform_steps"] = steps
                query_group = str(
                    result.get("query_group", current_source.get("query_group", ""))
                ).strip()
                if query_group:
                    target["query_group"] = query_group
                else:
                    target.pop("query_group", None)
                if query_group != str(current_source.get("query_group", "")):
                    metadata_change_ids.add(source_id)
                step_metadata = result.get(
                    "step_metadata", current_source.get("step_metadata", [])
                )
                if step_metadata != current_source.get("step_metadata", []):
                    metadata_change_ids.add(source_id)
                target["step_metadata"] = deepcopy(step_metadata)
                accepted_type_map = result.get("column_types")
                if (
                    source_id in new_source_ids
                    and current_source.get("query_definition", {}).get("operation") == "reference"
                    and source_id in session_type_maps
                ):
                    accepted_type_map = session_type_maps[source_id]
                type_map = (
                    dict(accepted_type_map)
                    if isinstance(accepted_type_map, dict)
                    else column_types_after_steps(
                        raw_candidate.headers,
                        steps,
                        output_headers=transformed.headers,
                    )
                )
                calculated_candidate, calculated_types = self._apply_calculated_columns(
                    source_id,
                    transformed,
                    project=next_project,
                    column_types=type_map,
                )
                type_map.update(calculated_types)
                table = self._model_table_for_source(next_project, source_id)
                if table is not None:
                    table["column_types"] = type_map
                else:
                    next_project.setdefault("model", {}).setdefault("tables", []).append({
                        "id": source_id,
                        "source_id": source_id,
                        "name": str(
                            target.get("query_name", target.get("name", "Table"))
                        ),
                        "column_types": type_map,
                    })
                raw_snapshots[source_id] = raw_candidate
                existing_steps = validate_steps(current_source.get("transform_steps", []))
                if steps != existing_steps:
                    step_change_ids.add(source_id)
                output_changed = calculated_candidate != self._loaded_candidates.get(source_id)
                is_derived_query = current_source.get("kind") == "query"
                # A refreshed dependent query is a derived preview, not an
                # independent staged edit. Rebuild it from the committed
                # upstream result below; only an explicit query-step edit may
                # become a query base candidate.
                if (
                    source_id in new_source_ids
                    or source_id in source_settings_change_ids
                    or steps != existing_steps
                    or (output_changed and not is_derived_query)
                    or source_id in parameter_change_sources
                    or source_id in function_change_sources
                ):
                    changes[source_id] = (current_source, result, steps)
                    base_candidates[source_id] = calculated_candidate

            affected_sqlite_source_ids = set(source_settings_change_ids)
            affected_sqlite_source_ids.update(
                source_id
                for source_id in new_source_ids
                if source_by_id.get(source_id, {}).get("kind") == "sqlite"
            )
            if self._sqlite_binding_conflict(
                next_project.get("data_sources", []),
                affected_sqlite_source_ids,
            ):
                self._set_status(
                    "This SQLite database table is already linked to another source in the project."
                )
                return False

            eligible_sources = [
                item for item in self._source_dependency_order(
                    next_project.get("data_sources", [])
                )
                if self._source_load_enabled(item)
                and (
                    str(item.get("id", "")) in self._loaded_candidates
                    or str(item.get("id", "")) in new_source_ids
                )
            ]
            selected_new_source = next(
                (
                    source_id for source_id, (_source, result, *_rest)
                    in validated_results.items()
                    if source_id in new_source_ids
                    and result.get("is_active")
                    and self._source_load_enabled(source_by_id[source_id])
                ),
                None,
            )
            if selected_new_source is not None:
                next_project["active_source_id"] = selected_new_source
            active_source = next((
                item for item in eligible_sources
                if str(item.get("id", "")) == str(self._active_source_id or "")
            ), None)
            if active_source is None:
                next_project["active_source_id"] = (
                    selected_new_source
                    or (str(eligible_sources[0]["id"]) if eligible_sources else None)
                )

            if not changes and not deleted_query_ids:
                # Close & Apply also refreshes the active query preview. Keep the
                # accepted raw snapshots so switching queries cannot restore stale rows.
                if metadata_change_ids or parameters_changed or functions_changed:
                    try:
                        next_project = validate_project(next_project)
                    except ProjectFileError as exc:
                        self._set_status(f"Could not apply Power Query query settings: {exc}")
                        return False
                    self._project = next_project
                    self._raw_candidates.update(raw_snapshots)
                    self._sync_active_source_after_session_settings()
                    self._dirty = True
                    self._refresh_model_view()
                    self._refresh_report()
                    self.stateChanged.emit()
                    if functions_changed and not parameters_changed and not metadata_change_ids:
                        self._set_status("Updated Power Query functions")
                    elif functions_changed and parameters_changed and not metadata_change_ids:
                        self._set_status("Updated Power Query parameters and functions")
                    elif parameters_changed and not metadata_change_ids:
                        self._set_status("Updated Power Query parameters")
                    elif parameters_changed:
                        self._set_status(
                            f"Updated Power Query parameters"
                            f"{' and functions' if functions_changed else ''} and settings for "
                            f"{len(metadata_change_ids)} quer"
                            f"{'y' if len(metadata_change_ids) == 1 else 'ies'}"
                        )
                    else:
                        self._set_status(
                            f"Updated query settings for {len(metadata_change_ids)} quer"
                            f"{'y' if len(metadata_change_ids) == 1 else 'ies'}"
                        )
                else:
                    self._raw_candidates.update(raw_snapshots)
                    self._set_status("Power Query previews are current; there are no query changes to apply.")
                return True

            # A new query's stored conversion steps are part of staging its
            # typed result against the current parent previews. It has no
            # previously saved output that can conflict with a parent edit.
            changed_ids = sorted(step_change_ids - new_source_ids)
            for index, left_id in enumerate(changed_ids):
                for right_id in changed_ids[index + 1:]:
                    if depends_on(left_id, right_id) or depends_on(right_id, left_id):
                        self._set_status(
                            "Apply transformations to dependent queries one at a time so each preview uses the latest upstream result."
                        )
                        return False

            next_project = validate_project(next_project)
            dependent_candidates, dependent_types = self._rebuild_query_dependents(
                next_project, base_candidates
            )
            for dependent_id, type_map in dependent_types.items():
                table = self._model_table_for_source(next_project, dependent_id)
                if table is not None:
                    table["column_types"] = type_map
            next_project = validate_project(next_project)
            relationship_candidates = dict(base_candidates)
            relationship_candidates.update(dependent_candidates)
            self._validate_loaded_relationship_candidates(
                next_project, relationship_candidates
            )
        except (
            StopIteration,
            OSError,
            ProjectFileError,
            QueryError,
            TransformationError,
            TypeError,
            ValueError,
        ) as exc:
            self._set_status(f"Could not apply the Power Query session: {exc}")
            return False

        credential_updates: dict[str, tuple[str, dict[str, Any]]] = {}
        for source_id, password in staged_sql_passwords.items():
            source = source_by_id.get(source_id, {})
            connection = dict(source.get("connection", {}))
            credential_ref = str(connection.get("credential_ref", ""))
            if not credential_ref:
                self._set_status("The staged SQL Server credential reference is missing.")
                return False
            previous = credential_updates.get(credential_ref)
            if previous is not None and previous[0] != password:
                self._set_status(
                    "Staged SQL Server sources cannot reuse one credential reference for different passwords."
                )
                return False
            credential_updates[credential_ref] = (password, connection)
        existing_credential_refs = {
            str(source.get("connection", {}).get("credential_ref", ""))
            for source in self._project.get("data_sources", [])
            if source.get("kind") == "sql_server"
        }
        if existing_credential_refs & credential_updates.keys():
            self._set_status(
                "A staged SQL Server source reused an existing credential reference. Reopen the connector and try again."
            )
            return False

        attempted_credentials: list[tuple[str, dict[str, Any]]] = []
        for credential_ref, (password, connection) in credential_updates.items():
            attempted_credentials.append((credential_ref, connection))
            try:
                set_sql_server_password(credential_ref, password, connection)
            except CredentialStoreError as exc:
                cleanup_failed = False
                for attempted_ref, attempted_connection in reversed(
                    attempted_credentials
                ):
                    self._sql_server_passwords.pop(
                        sql_server_credential_account(
                            attempted_ref, attempted_connection
                        ),
                        None,
                    )
                    try:
                        delete_sql_server_password(
                            attempted_ref, attempted_connection
                        )
                    except CredentialStoreError:
                        cleanup_failed = True
                suffix = (
                    " Some staged Keychain entries could not be removed."
                    if cleanup_failed else ""
                )
                self._set_status(
                    f"Could not save SQL Server credentials: {exc}.{suffix}"
                )
                return False
        for credential_ref, (password, connection) in credential_updates.items():
            self._sql_server_passwords[
                sql_server_credential_account(credential_ref, connection)
            ] = password

        self._project = next_project
        credential_cleanup_failed = False
        remaining_credential_refs = {
            str(source.get("connection", {}).get("credential_ref", ""))
            for source in next_project.get("data_sources", [])
            if source.get("kind") == "sql_server"
        }
        for credential_ref, connection in deleted_sql_credentials:
            if not credential_ref or credential_ref in remaining_credential_refs:
                continue
            self._sql_server_passwords.pop(
                sql_server_credential_account(credential_ref, connection), None
            )
            try:
                delete_sql_server_password(credential_ref, connection)
            except CredentialStoreError:
                credential_cleanup_failed = True
        for deleted_id in deleted_query_ids:
            self._loaded_candidates.pop(deleted_id, None)
            self._raw_candidates.pop(deleted_id, None)
            self._source_load_errors.pop(deleted_id, None)
        self._raw_candidates.update(raw_snapshots)
        self._loaded_candidates.update(dependent_candidates)
        for updated_id in dependent_candidates:
            self._source_load_errors.pop(updated_id, None)
        self._sync_active_source_after_session_settings()
        active_candidate = dependent_candidates.get(str(self._active_source_id or ""))
        if active_candidate is not None and self._active_source_id:
            active_source = source_by_id.get(self._active_source_id)
            active_path = (
                self._resolved_source_path(active_source)
                if active_source and active_source.get("kind") not in PATHLESS_SOURCE_KINDS
                else None
            )
            self._install_source(active_path, self._active_source_id, active_candidate)
        self._source_warning = self._compose_source_warning()
        self._current_region = None
        self._dirty = True
        self._refresh_model_view()
        self._refresh_report()
        self.stateChanged.emit()
        recent_source_errors: list[str] = []
        for source_id in new_source_ids:
            source = source_by_id.get(source_id, {})
            if not source.get("path"):
                continue
            try:
                self._recent_source_store.add(
                    self._resolved_source_path(source),
                    str(source.get("kind", "")),
                    dict(source.get("parser_options", {})),
                    display_name=str(source.get("name", "")),
                )
            except (OSError, TypeError, ValueError) as exc:
                recent_source_errors.append(str(exc))
        if deleted_query_ids and changes:
            self._set_status(
                f"Applied changes to {len(changes)} quer{'y' if len(changes) == 1 else 'ies'} "
                f"and deleted {len(deleted_query_ids)} quer{'y' if len(deleted_query_ids) == 1 else 'ies'}"
            )
        elif deleted_query_ids:
            self._set_status(
                f"Deleted {len(deleted_query_ids)} quer{'y' if len(deleted_query_ids) == 1 else 'ies'}"
            )
        else:
            self._set_status(
                f"Applied Power Query changes to {len(changes)} quer{'y' if len(changes) == 1 else 'ies'}"
            )
        if recent_source_errors:
            self._set_status(
                self.statusMessage + "; recent source history could not be saved"
            )
        if credential_cleanup_failed:
            self._set_status(
                self.statusMessage + "; an unused SQL Server credential remains in Keychain"
            )
        return True

    def _sync_active_source_after_session_settings(self) -> None:
        """Keep the data view on a model-loaded source after query load changes."""
        active_source_id = self._project.get("active_source_id")
        if active_source_id == self._active_source_id:
            return
        if not active_source_id:
            self._clear_source(clear_selection=True)
            return
        source_id = str(active_source_id)
        candidate = self._loaded_candidates.get(source_id)
        source = next(
            (item for item in self._project.get("data_sources", [])
             if str(item.get("id", "")) == source_id),
            None,
        )
        if candidate is None or source is None or not self._source_load_enabled(source):
            self._clear_source(clear_selection=True)
            return
        path = (
            self._resolved_source_path(source)
            if source.get("kind") not in PATHLESS_SOURCE_KINDS
            else None
        )
        self._install_source(path, source_id, candidate)
        self._source_warning = self._compose_source_warning()

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
            query_type_maps: dict[str, dict[str, str]] = {}
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
                    raw, source.get("transform_steps", []),
                    parameters=parameter_values(self._project.get("query_parameters", []), self._project.get("query_functions", [])),
                )
                definition = source.get("query_definition", {})
                input_types: dict[str, str] = (
                    self._query_input_column_types(
                        source,
                        self._project,
                        candidate=raw,
                        dependency_types=query_type_maps,
                    )
                    if kind == "query"
                    else infer_column_types(raw.headers, raw.rows)
                )
                base_types = column_types_after_steps(
                    raw.headers,
                    source.get("transform_steps", []),
                    output_headers=query_candidate.headers,
                    initial_types=input_types,
                )
                query_type_maps[source_id] = base_types
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
                type_map = dict(query_type_maps[source_id])
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
            self._validate_loaded_relationship_candidates(next_project, refreshed)
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
        self._raw_candidates.update(raw_candidates)
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
            "visual_interactions": [],
            "hidden": False,
        }
        pages.append(page)
        self._active_page_id = page["id"]
        self._project["report"]["active_page_id"] = page["id"]
        self._cross_filters.clear()
        self._selected_visual = ""
        self._selected_visual_ids.clear()
        self._creating_visual = False
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
                self._cross_filters.clear()
                self._selected_visual = ""
                self._selected_visual_ids.clear()
                self._creating_visual = False
            self._dirty = True
            self._refresh_report()
            self.stateChanged.emit()
            self._set_status(f"Deleted {deleted_name}")

    @Slot(str)

    @Slot(str, int, int)
    def move_visual(self, visual_id: str, x: int, y: int) -> None:
        page = self._active_page()
        if page is None:
            return
        visuals = page.get("visuals", [])
        visual = next((
            item for item in visuals
            if isinstance(item, dict) and item.get("id") == visual_id
        ), None)
        if visual is None:
            return
        next_x = max(0, int(x))
        next_y = max(0, int(y))
        delta_x = next_x - float(visual.get("x", 0))
        delta_y = next_y - float(visual.get("y", 0))
        group_id = visual.get("group_id")
        for item in visuals:
            if isinstance(item, dict) and (
                item is visual or (group_id and item.get("group_id") == group_id)
            ):
                item["x"] = max(0.0, float(item.get("x", 0)) + delta_x)
                item["y"] = max(0.0, float(item.get("y", 0)) + delta_y)
        self._dirty = True
        self.stateChanged.emit()


    @Slot(str, str)
    def add_field_to_well(self, well_name: str, field_name: str) -> None:
        if not self._selected_visual:
            return
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        table_id = self._active_model_table_id()
        if visual is None or well_name not in {
            str(item["name"]) for item in self.activeVisualWells
        }:
            self._set_status("Choose an available field well first.")
            return
        measure_name = _visual_measure_name(field_name)
        is_measure = measure_name is not None
        if is_measure:
            actual_measure = next((
                str(item["name"])
                for item in self._project.get("model", {}).get("measures", [])
                if str(item.get("name", "")).casefold() == measure_name.casefold()
            ), None)
            if actual_measure is None:
                self._set_status("That DAX measure is no longer available.")
                return
            field_name = _visual_measure_binding(actual_measure)
            if visual.get("type") == "slicer":
                self._set_status(
                    "A Slicer needs a column field so its values can filter the report."
                )
                return
            allowed_measure_wells = {
                "Y-axis", "Column Y-axis", "Line Y-axis", "Value", "Minimum",
                "Maximum", "Target", "Indicator", "Target goals", "Fields", "Values",
            }
            if well_name not in allowed_measure_wells or visual.get("type") == "scatter":
                self._set_status(
                    "Add DAX measures to a visual value well. Category, map, and scatter wells use columns."
                )
                return
        if not table_id or (not is_measure and field_name not in self._headers):
            self._set_status("Choose a field from the loaded table.")
            return
        bound_table_id = str(visual.get("table_id", ""))
        if bound_table_id and bound_table_id != table_id:
            self._set_status("This visual is bound to another table. Select that table to add fields.")
            return

        fields = visual.setdefault("fields", {})
        well_fields = fields.setdefault(well_name, [])
        table_field_well = visual.get("type") == "table" and well_name == "Fields"
        if field_name in well_fields:
            return
        if is_measure and well_fields and not table_field_well:
            self._set_status("This value well uses one DAX measure at a time.")
            return
        if (
            not is_measure
            and not table_field_well
            and well_name in {
                "Y-axis", "Column Y-axis", "Line Y-axis", "Value", "Minimum",
                "Maximum", "Target", "Indicator", "Target goals", "Fields", "Values",
            }
            and any(_visual_measure_name(item) is not None for item in well_fields)
        ):
            self._set_status("Remove the DAX measure before adding a column to this value well.")
            return
        if visual.get("type") == "card" and well_name == "Fields" and well_fields:
            self._set_status("A Card visual uses one field. Remove the current field to replace it.")
            return
        if visual.get("type") == "matrix" and well_name in {"Rows", "Columns", "Values"} and well_fields:
            self._set_status("This Matrix visual supports one field in each row, column, and value well.")
            return
        if visual.get("type") == "scatter" and well_name in {"X-axis", "Y-axis", "Legend", "Details"} and well_fields:
            self._set_status("This Scatter chart supports one field in each axis, legend, and details well.")
            return
        if visual.get("type") == "lineClusteredColumn" and well_name in {"Column Y-axis", "Line Y-axis"} and well_fields:
            self._set_status("This Combo chart supports one field in each value well.")
            return
        if visual.get("type") == "gauge" and well_name in {"Value", "Minimum", "Maximum", "Target"} and well_fields:
            self._set_status("This Gauge supports one field in each value well.")
            return
        if visual.get("type") == "kpi" and well_name in {"Indicator", "Trend axis", "Target goals"} and well_fields:
            self._set_status("This KPI supports one field in each indicator, trend, and target well.")
            return
        if visual.get("type") == "map" and well_name in {"Location", "Latitude", "Longitude", "Size", "Legend"} and well_fields:
            self._set_status("This Map supports one field in each location, coordinate, size, and legend well.")
            return

        visual.setdefault("table_id", table_id)
        well_fields.append(field_name)
        if not is_measure and well_name in {
            "Y-axis", "Column Y-axis", "Line Y-axis", "Value", "Minimum",
            "Maximum", "Target", "Indicator", "Target goals",
        } and visual.get("type") != "scatter":
            visual.setdefault("field_aggregations", {}).setdefault(field_name, "sum")
        elif not is_measure and visual.get("type") == "card" and well_name == "Fields":
            has_numeric = any(_report_number(row.get(field_name)) is not None for row in self._rows)
            visual.setdefault("field_aggregations", {}).setdefault(
                field_name, "sum" if has_numeric else "count"
            )
        elif not is_measure and visual.get("type") == "matrix" and well_name == "Values":
            has_numeric = any(_report_number(row.get(field_name)) is not None for row in self._rows)
            visual.setdefault("field_aggregations", {}).setdefault(
                field_name, "sum" if has_numeric else "count"
            )
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str, str)
    def remove_field_from_well(self, well_name: str, field_name: str) -> None:
        if not self._selected_visual:
            return
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        if visual is None:
            return
        well_fields = visual.get("fields", {}).get(well_name, [])
        if field_name not in well_fields:
            return
        well_fields.remove(field_name)
        if well_name in {
            "Y-axis", "Column Y-axis", "Line Y-axis", "Value", "Minimum",
            "Maximum", "Target", "Indicator", "Target goals",
        } or (
            well_name == "Fields" and visual.get("type") == "card"
        ) or (
            well_name == "Values" and visual.get("type") == "matrix"
        ):
            visual.get("field_aggregations", {}).pop(field_name, None)
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str, str, str)
    def set_field_aggregation(
        self, well_name: str, field_name: str, aggregation: str
    ) -> None:
        if _visual_measure_name(field_name) is not None:
            self._set_status("DAX measures are already evaluated values and cannot be re-aggregated.")
            return
        key = aggregation.strip().casefold()
        if key not in _VISUAL_FIELD_AGGREGATIONS:
            self._set_status("Choose Sum, Count, or Average for this field.")
            return
        page = self._active_page()
        visual = next((
            item for item in (page.get("visuals", []) if page else [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        allowed_well = (
            well_name in {"Y-axis", "Column Y-axis", "Line Y-axis"}
            or (
                well_name in {"Value", "Minimum", "Maximum", "Target"}
                and visual is not None and visual.get("type") == "gauge"
            )
            or (
                well_name in {"Indicator", "Target goals"}
                and visual is not None and visual.get("type") == "kpi"
            )
            or (well_name == "Fields" and visual is not None and visual.get("type") == "card")
            or (well_name == "Values" and visual is not None and visual.get("type") == "matrix")
        )
        if visual is None or not allowed_well or field_name not in visual.get("fields", {}).get(well_name, []):
            self._set_status("Choose an assigned field first.")
            return
        aggregations = visual.setdefault("field_aggregations", {})
        if aggregations.get(field_name, "sum") == key:
            return
        aggregations[field_name] = key
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()

    @Slot(str, str)
    def set_visual_type(self, title: str, v_type: str) -> None:
        page = self._project["report"]["pages"][self.activePageIndex]
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == title:
                visual["type"] = v_type
                self._report_filter_context_cache.clear()
                self._dirty = True
                self.stateChanged.emit()
                return

    @Slot()
    def begin_new_visual(self) -> None:
        self._selected_visual = ""
        self._selected_visual_ids = []
        self._creating_visual = True
        self.stateChanged.emit()
        self._set_status("Choose a supported visual type to add it to the report.")

    @Slot(str)
    def add_blank_visual(self, visual_type: str) -> None:
        labels = {
            "bar": "Bar chart",
            "column": "Column chart",
            "stackedBar": "Stacked bar chart",
            "stackedColumn": "Stacked column chart",
            "bar100": "100% stacked bar chart",
            "column100": "100% stacked column chart",
            "stackedArea": "Stacked area chart",
            "area100": "100% stacked area chart",
            "waterfall": "Waterfall chart",
            "treemap": "Treemap",
            "ribbon": "Ribbon chart",
            "matrix": "Matrix",
            "scatter": "Scatter chart",
            "line": "Line chart",
            "lineClusteredColumn": "Line and clustered column chart",
            "gauge": "Gauge",
            "kpi": "KPI",
            "map": "Map",
            "area": "Area chart",
            "pie": "Pie chart",
            "donut": "Donut chart",
            "funnel": "Funnel chart",
            "card": "Card",
            "table": "Table",
            "slicer": "Slicer",
        }
        base_title = labels.get(visual_type)
        if base_title is None:
            self._set_status("Choose a supported visual type.")
            return
        page = self._active_page()
        if page is None:
            return
        visuals = page.setdefault("visuals", [])
        existing_titles = {
            str(item.get("title", "")) for item in visuals if isinstance(item, dict)
        }
        title = base_title
        suffix = 2
        while title in existing_titles:
            title = f"{base_title} {suffix}"
            suffix += 1

        if visual_type == "slicer":
            width, height = 260, 300
        elif visual_type == "card":
            width, height = 250, 150
        else:
            width, height = 330, 248
        position = None
        for y in range(14, 720 - height + 1, 20):
            for x in range(14, 1280 - width + 1, 20):
                overlaps = False
                for item in visuals:
                    if not isinstance(item, dict):
                        continue
                    other_x = float(item.get("x", 0))
                    other_y = float(item.get("y", 0))
                    other_width = float(item.get("width", 300))
                    other_height = float(item.get("height", 200))
                    if (
                        x < other_x + other_width
                        and x + width > other_x
                        and y < other_y + other_height
                        and y + height > other_y
                    ):
                        overlaps = True
                        break
                if not overlaps:
                    position = (x, y)
                    break
            if position is not None:
                break
        if position is None:
            position = (14, 14)

        self._creating_visual = False
        self.add_visual(visual_type, title, *position, width, height)

    @Slot(str, "QVariant")
    def set_visual_property(self, property_key: str, value: object) -> None:
        if not self._selected_visual:
            return
        page = self._active_page()
        if page is None:
            return
        visual = next((
            item for item in page.get("visuals", [])
            if isinstance(item, dict) and item.get("title") == self._selected_visual
        ), None)
        if visual is None:
            return
        if property_key == "title":
            normalized: object = str(value).strip()
            if not normalized:
                self._set_status("A visual needs a title.")
                return
            if any(
                item is not visual and isinstance(item, dict)
                and item.get("title") == normalized
                for item in page.get("visuals", [])
            ):
                self._set_status("Each visual on a page needs a unique title.")
                return
        elif property_key in {"x", "y", "width", "height"}:
            if isinstance(value, bool):
                self._set_status("Enter a finite number for the visual position or size.")
                return
            try:
                normalized = float(value)
            except (TypeError, ValueError):
                self._set_status("Enter a finite number for the visual position or size.")
                return
            if not math.isfinite(normalized):
                self._set_status("Enter a finite number for the visual position or size.")
                return
            normalized = max(10.0 if property_key in {"width", "height"} else 0.0, normalized)
        elif property_key == "color":
            normalized = str(value)
            if (
                len(normalized) != 7
                or normalized[0] != "#"
                or any(character not in "0123456789abcdefABCDEF" for character in normalized[1:])
            ):
                self._set_status("Enter a color in #RRGGBB format.")
                return
        elif property_key in {"show_data_labels", "show_legend"}:
            if type(value) is not bool:
                self._set_status("Choose whether to show this visual element.")
                return
            normalized = value
        elif property_key == "text" and visual.get("type") in {"button", "text_box"}:
            normalized = str(value)
        elif property_key == "actionUrl" and visual.get("type") == "button":
            normalized = str(value)
        elif property_key == "image_path" and visual.get("type") == "image":
            image_path = str(value).strip()
            if image_path:
                path = Path(image_path).expanduser().resolve()
                if not path.is_file() or QImage(str(path)).isNull():
                    self._set_status("Choose a readable image file.")
                    return
                normalized = str(path)
            else:
                normalized = ""
        else:
            self._set_status("This visual property is unavailable.")
            return

        previous = visual.get(property_key)
        if previous == normalized:
            return
        if property_key == "title":
            old_title = str(visual.get("title", ""))
            self._selected_visual = str(normalized)
            for visual_filter in page.get("visual_filters", []):
                if visual_filter.get("visual_name") == old_title:
                    visual_filter["visual_name"] = str(normalized)
            self._cross_filters.pop(old_title, None)
        visual[property_key] = normalized
        self._report_filter_context_cache.clear()
        self._refresh_report()
        self._dirty = True
        self.stateChanged.emit()

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
            removed_visual = visuals[index_to_remove]
            name = removed_visual.get("title", "")
            removed_id = self._visual_persistence_id(removed_visual)
            del visuals[index_to_remove]
            page["visual_interactions"] = [
                interaction
                for interaction in page.get("visual_interactions", [])
                if interaction.get("source_visual_id") != removed_id
                and interaction.get("target_visual_id") != removed_id
            ]
            if not any(
                isinstance(visual, dict) and visual.get("title") == name
                for visual in visuals
            ):
                self._cross_filters.pop(str(name), None)
            self._selected_visual_ids = [
                selected_id for selected_id in self._selected_visual_ids
                if selected_id != removed_id
            ]
            if self._selected_visual == name:
                selected = next((
                    visual for visual in visuals
                    if isinstance(visual, dict)
                    and str(visual.get("id", "")) in self._selected_visual_ids
                ), None)
                self._selected_visual = str(selected.get("title", "")) if selected else ""
            remaining_group = removed_visual.get("group_id")
            if remaining_group:
                members = [
                    visual for visual in visuals
                    if isinstance(visual, dict)
                    and visual.get("group_id") == remaining_group
                ]
                if len(members) == 1:
                    members[0].pop("group_id", None)
            if not self._selected_visual_ids:
                self._selected_visual = ""
                self._creating_visual = False
            self._dirty = True
            self._refresh_report()
            self.stateChanged.emit()
            self._set_status("Removed visual")

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
            "height": height,
            "show_data_labels": False,
            "show_legend": False,
        })
        self._dirty = True
        self._selected_visual = title
        self._selected_visual_ids = [new_id]
        self._creating_visual = False
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Added visual {title}")
        return new_id

    @Slot()
    def insert_image(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            None,
            "Insert image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)",
        )
        if not path_text:
            return
        image_path = Path(path_text).expanduser().resolve()
        if not image_path.is_file() or QImage(str(image_path)).isNull():
            self._set_status("Choose a readable image file.")
            return

        base_title = image_path.stem or "Image"
        title = base_title
        existing_titles = {
            str(item.get("title", ""))
            for item in self._active_page().get("visuals", [])
            if isinstance(item, dict)
        }
        suffix = 2
        while title in existing_titles:
            title = f"{base_title} {suffix}"
            suffix += 1
        visual_id = self.add_visual("image", title, 100, 100, 250, 150)
        visual = next(
            item for item in self._active_page().get("visuals", [])
            if isinstance(item, dict) and item.get("id") == visual_id
        )
        visual["image_path"] = str(image_path)
        self.stateChanged.emit()

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
        self._cross_filters.clear()
        self._selected_visual = ""
        self._selected_visual_ids.clear()
        self._creating_visual = False
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
        added = not any(
            isinstance(v, dict) and v.get("title") == visual_name for v in visuals
        )
        if added:
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
            self._refresh_report()
        selected = next((
            visual for visual in visuals
            if isinstance(visual, dict) and visual.get("title") == visual_name
        ), None)
        self._selected_visual = visual_name
        self._selected_visual_ids = [str(selected.get("id", ""))] if selected else []
        self._creating_visual = False
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
            f"Analytics Studio projects use the versioned .npa JSON format (currently v{FORMAT_VERSION}). "
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
        for page in document["report"].get("pages", []):
            for visual in page.get("visuals", []):
                image_path = visual.get("image_path") if isinstance(visual, dict) else None
                if isinstance(image_path, str) and image_path:
                    visual["image_path"] = self._source_path_for_save(image_path, path)

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
        self._cross_filters.clear()
        self._active_source_id = None
        self._active_source_path = None
        self._active_source_kind = None
        self._active_parser_options = {}
        self._loaded_candidates = {}
        self._raw_candidates = {}
        self._source_load_errors = {}
        self._selected_visual = ""
        self._selected_visual_ids.clear()
        self._creating_visual = False
        self._clipboard_visual_config = None
        self._clipboard_format_config = None
        self._format_painter_active = False
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
        self._report_filter_context_cache.clear()
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
        self._report_theme = self._project.get("report", {}).get("theme", "Default")
        self._themes = REPORT_THEMES
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
        ) -> Decimal | None:
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
                formatted = (
                    _format_report_number(value) if value is not None else "—"
                )
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
            if visual_name in visuals_with_filters or self._cross_filters:
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
                        self._visual_kpis[visual_name] = (
                            _format_report_number(visual_value)
                            if visual_value is not None else "—"
                        )
                else:
                    self._visual_kpis[visual_name] = standard_kpis(visual_rows).get(kpi_name, "—")

        self._filter_context_error = "; ".join(dict.fromkeys(filter_errors))

    def _measure_value_for_visual_group(
        self,
        measure_name: str,
        table_context: list[dict[str, Any]],
        filter_table_ids: set[str],
        group_filters: dict[str, str | set[str]],
        group_table_id: str,
    ) -> Decimal | None:
        """Evaluate one saved measure with chart-category filters applied."""
        contexts: list[dict[str, Any]] = []
        contexts_by_id: dict[str, dict[str, Any]] = {}
        for source_context in table_context:
            context = dict(source_context)
            context["filter_column_rows"] = {
                str(column): frozenset(indexes)
                for column, indexes in source_context.get(
                    "filter_column_rows", {}
                ).items()
            }
            context["filter_column_blank_allowed"] = dict(
                source_context.get("filter_column_blank_allowed", {})
            )
            contexts.append(context)
            contexts_by_id[str(context["id"])] = context

        for table_id, context in contexts_by_id.items():
            if table_id != group_table_id:
                continue
            table_filters = {
                column: value
                for column, value in group_filters.items()
                if column in context["headers"]
            }
            if not table_filters:
                continue
            rows = context["rows"]
            count = len(rows)
            column_rows = dict(context.get("filter_column_rows", {}))
            blank_allowed = dict(context.get("filter_column_blank_allowed", {}))
            for column, value in table_filters.items():
                selected_values = value if isinstance(value, set) else {value}
                matching = frozenset(
                    index for index, row in enumerate(rows)
                    if ("" if row.get(column) is None else str(row.get(column)))
                    in selected_values
                )
                existing = column_rows.get(column)
                column_rows[column] = (
                    matching if existing is None else matching & existing
                )
                blank_allowed[column] = (
                    "" in selected_values
                    and blank_allowed.get(column, True)
                )
            context["filter_column_rows"] = column_rows
            context["filter_column_blank_allowed"] = blank_allowed
            context["filter_context_complete"] = True
            base_rows = context.get("filter_rows")
            base_row_ids = None if base_rows is None else {id(row) for row in base_rows}
            context["filter_rows"] = [
                row
                for index, row in enumerate(rows)
                if (base_row_ids is None or id(row) in base_row_ids)
                and all(index in indexes for indexes in column_rows.values())
            ]
            filter_table_ids = {*filter_table_ids, table_id}

        active_table_id = self._active_model_table_id()
        active_context = contexts_by_id.get(active_table_id)
        if active_context is None:
            raise MeasureError("The active model table is unavailable for this visual.")
        target_measure = next((
            str(item["name"])
            for item in self._project.get("model", {}).get("measures", [])
            if str(item.get("name", "")).casefold() == measure_name.casefold()
        ), None)
        if target_measure is None:
            raise MeasureError(f"Measure {measure_name!r} no longer exists.")
        active_rows = active_context.get("filter_rows", active_context["rows"])
        values = evaluate_measures(
            self._project.get("model", {}).get("measures", []),
            list(active_rows),
            list(active_context["headers"]),
            self._active_model_table_name(),
            measure_names=[target_measure],
            table_context=contexts,
            relationships=self._project.get("model", {}).get("relationships", []),
            filter_table_ids=filter_table_ids,
            active_table_id=active_table_id or None,
        )
        return values[target_measure]

    def _measure_visual_series(
        self,
        measure_name: str,
        category_column: str,
        legend_column: str | None,
        visual_rows: list[dict[str, Any]],
        table_context: list[dict[str, Any]],
        filter_table_ids: set[str],
        group_table_id: str,
        *,
        stacked: bool,
    ) -> list[dict[str, object]]:
        if not category_column:
            return []
        groups: set[tuple[str, str]] = set()
        for row in visual_rows:
            category = "" if row.get(category_column) is None else str(
                row.get(category_column)
            )
            legend = (
                "" if legend_column and row.get(legend_column) is None
                else str(row.get(legend_column, "")) if legend_column else ""
            )
            groups.add((category, legend))
        grouped_values: dict[tuple[str, str], Decimal | None] = {}
        for category, legend in groups:
            filters = {category_column: category}
            if stacked and legend_column:
                filters[legend_column] = legend
            grouped_values[(category, legend)] = self._measure_value_for_visual_group(
                measure_name, table_context, set(filter_table_ids), filters,
                group_table_id,
            )
        categories = sorted({category for category, _ in groups}, key=str.casefold)
        if not stacked or not legend_column:
            series: list[dict[str, object]] = []
            for category in categories:
                value = grouped_values.get((category, ""))
                if value is not None:
                    series.append({"label": category, "value": float(value)})
            return series
        legends = sorted({legend for _, legend in groups}, key=str.casefold)
        series = []
        for category in categories:
            present = [
                (legend, value)
                for legend in legends
                if (value := grouped_values.get((category, legend))) is not None
            ]
            if not present:
                continue
            series.append({
                "label": category,
                "value": float(sum(
                    (value for _legend, value in present), Decimal(0)
                )),
                "segments": [
                    {"label": legend, "value": float(value)}
                    for legend, value in present
                ],
            })
        return series

    def _generate_dynamic_visual_series(
        self,
        visual_name: str,
        *,
        include_highlights: bool = False,
        value_well: str | None = None,
    ) -> list[dict[str, object]]:
        page = self._active_page()
        if not page:
            return []
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == visual_name), None)
        if not visual:
            return []
            
        fields = visual.get("fields", {})
        x_axis = fields.get("X-axis", [])
        if visual.get("type") == "kpi":
            x_axis = fields.get("Trend axis", [])
        if value_well is None:
            value_well = (
                "Column Y-axis"
                if visual.get("type") == "lineClusteredColumn"
                else "Indicator" if visual.get("type") == "kpi" else "Y-axis"
            )
        if visual.get("type") == "lineClusteredColumn" and not fields.get(value_well):
            return []
        y_axis = fields.get(value_well, [])
        if visual.get("type") == "slicer" and not x_axis and not y_axis:
            x_axis = fields.get("Fields", [])

        # If no fields are mapped in dynamic wells, fall back to legacy series for initial views
        if not x_axis and not y_axis:
            if visual_name == "Monthly revenue":
                return self._monthly_visual_series.get(visual_name, self._monthly_series)
            elif visual_name == "Region revenue":
                return self._region_visual_series.get(visual_name, self._region_series)
            return []

        def well_column(bindings: Any) -> str | None:
            if not isinstance(bindings, list) or not bindings:
                return None
            binding = bindings[0]
            if isinstance(binding, dict):
                value = binding.get("column")
            elif isinstance(binding, (list, tuple)):
                value = binding[1] if len(binding) > 1 else binding[0]
            else:
                value = binding
            return str(value) if value is not None else None

        x_col = well_column(x_axis)
        y_col = well_column(y_axis)
        legend_col = well_column(fields.get("Legend", []))
        aggregation = str(
            visual.get("field_aggregations", {}).get(y_col, "sum")
        ).casefold()
        if aggregation not in _VISUAL_FIELD_AGGREGATIONS:
            aggregation = "sum"
        bound_table_id = str(visual.get("table_id") or self._active_model_table_id())
        visual_rows_by_table, visual_measure_context, visual_filter_table_ids = self._report_filter_context(
            visual_name, include_highlights=include_highlights
        )
        visual_rows = visual_rows_by_table.get(bound_table_id)
        if visual_rows is None:
            return []

        if visual.get("type") == "slicer":
            if not x_col or _visual_measure_name(x_col) is not None:
                return []
            values = sorted({
                "" if row.get(x_col) is None else str(row.get(x_col, ""))
                for row in visual_rows
            }, key=str.casefold)
            return [{"label": value, "value": 1.0} for value in values]

        visual_rows = self._apply_visual_top_n_rows(
            visual_name, visual_rows, bound_table_id
        )

        measure_name = _visual_measure_name(y_col)
        if measure_name:
            stacked = visual.get("type") in {
                "stackedBar", "stackedColumn", "bar100", "column100",
                "stackedArea", "area100", "ribbon",
            }
            try:
                return self._measure_visual_series(
                    measure_name,
                    x_col or "",
                    legend_col,
                    visual_rows,
                    visual_measure_context,
                    visual_filter_table_ids,
                    bound_table_id,
                    stacked=stacked,
                )
            except (MeasureError, KeyError, TypeError, ValueError):
                return []

        if visual.get("type") in {
            "stackedBar", "stackedColumn", "bar100", "column100",
            "stackedArea", "area100", "ribbon",
        }:
            if not x_col or not y_col:
                return []

            from collections import defaultdict
            from decimal import Decimal

            grouped: defaultdict[tuple[str, str], Decimal] = defaultdict(Decimal)
            counts: defaultdict[tuple[str, str], int] = defaultdict(int)
            for row in visual_rows:
                raw_value = row.get(y_col)
                if aggregation == "count":
                    if raw_value is None or not str(raw_value).strip():
                        continue
                    amount = Decimal(1)
                elif raw_value is not None and str(raw_value).strip():
                    try:
                        amount = Decimal(str(raw_value).replace("$", "").replace(",", "").strip())
                    except Exception:
                        continue
                    if not amount.is_finite():
                        continue
                else:
                    continue

                category_value = row.get(x_col)
                category = "(Blank)" if category_value is None or not str(category_value).strip() else str(category_value)
                legend_value = row.get(legend_col) if legend_col else y_col
                segment = "(Blank)" if legend_col and (legend_value is None or not str(legend_value).strip()) else str(legend_value)
                key = (category, segment)
                grouped[key] += amount
                counts[key] += 1

            if aggregation == "average":
                grouped = defaultdict(
                    Decimal,
                    {
                        key: total / counts[key]
                        for key, total in grouped.items()
                        if counts[key]
                    },
                )

            categories = sorted({category for category, _ in grouped}, key=str.casefold)
            segments = sorted({segment for _, segment in grouped}, key=str.casefold)
            return [
                {
                    "label": category,
                    "value": float(sum((grouped.get((category, segment), Decimal(0)) for segment in segments), Decimal(0))),
                    "segments": [
                        {
                            "label": segment,
                            "value": float(grouped.get((category, segment), Decimal(0))),
                        }
                        for segment in segments
                    ],
                }
                for category in categories
            ]

        from collections import defaultdict
        from decimal import Decimal
        aggregated: defaultdict[str, Decimal] = defaultdict(Decimal)
        value_counts: defaultdict[str, int] = defaultdict(int)
        for row in visual_rows:
            if y_col:
                val = row.get(y_col, "")
                if aggregation == "count":
                    if val is None or not str(val).strip():
                        continue
                    amount = Decimal(1)
                elif val is not None and str(val).strip():
                    # Strip currency symbols and commas if it's a string, then parse
                    val_str = str(val).replace("$", "").replace(",", "").strip()
                    try:
                        amount = Decimal(val_str)
                    except Exception:
                        continue
                    if not amount.is_finite():
                        continue
                else:
                    continue
            else:
                amount = Decimal(1)
            
            key = str(row.get(x_col, "")) if x_col else "(Blank)"
            if key:
                aggregated[key] += amount
                value_counts[key] += 1

        if aggregation == "average":
            aggregated = defaultdict(
                Decimal,
                {
                    key: total / value_counts[key]
                    for key, total in aggregated.items()
                    if value_counts[key]
                },
            )

        if visual.get("type", "bar") in {
            "column", "area", "line", "lineClusteredColumn", "waterfall", "ribbon", "kpi",
        }:
            if visual.get("type") == "kpi":
                def kpi_sort_key(item: tuple[str, Decimal]) -> tuple[int, Decimal | str]:
                    try:
                        numeric = Decimal(item[0])
                    except (DecimalException, ValueError):
                        return (1, item[0].casefold())
                    return (0, numeric) if numeric.is_finite() else (1, item[0].casefold())

                ordered_values = sorted(aggregated.items(), key=kpi_sort_key)
            else:
                ordered_values = sorted(aggregated.items())
            series = [{"label": key, "value": float(value)} for key, value in ordered_values]
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

    @Property(str, notify=stateChanged)
    def reportTheme(self) -> str:  # noqa: N802
        return self._report_theme

    @Slot(str)
    def set_report_theme(self, theme_name: str) -> None:
        if theme_name not in self._themes: return
        report = self._project.get("report", {})
        if report.get("theme", "Default") == theme_name:
            return
        report["theme"] = theme_name
        self._report_theme = theme_name
        colors = self._themes[theme_name]
        
        # Apply theme colors to visualizations
        for page in self._project["report"]["pages"]:
            for v in page.get("visuals", []):
                 # Let's say all charts get primary color
                 if isinstance(v, dict):
                     v["color"] = colors["primary"]
        self._dirty = True
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status(f"Theme applied: {theme_name}")

    @Slot(str, result=bool)
    def open_button_action(self, action_url: str) -> bool:
        """Open an absolute HTTP(S) button URL through the desktop handler."""
        target = QUrl(str(action_url).strip())
        if (
            not target.isValid()
            or target.scheme().casefold() not in {"http", "https"}
            or not target.host()
        ):
            self._set_status("Button actions require an absolute HTTP or HTTPS URL.")
            return False
        opened = _open_external_url(target)
        if not opened:
            self._set_status("Could not open the button URL.")
            return False
        self._set_status(f"Opened {target.toString()}")
        return True

    @Slot(str, str)
    def toggle_cross_filter(self, visual_title: str, label: str) -> None:
        selected_list = self._cross_filters.setdefault(visual_title, [])
        if label in selected_list:
            selected_list.remove(label)
        else:
            selected_list.append(label)
            
        if not selected_list:
            del self._cross_filters[visual_title]

        self._refresh_report()
        self.stateChanged.emit()

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
        new_visual.pop("group_id", None)
        
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
        self._selected_visual_ids = [str(new_visual["id"])]
        self._refresh_report()
        self.stateChanged.emit()
        self._set_status("Pasted visual")

    @Slot()
    def copy_format(self) -> None:
        if not self._selected_visual:
            return
        page = self._active_page()
        visual = next((v for v in page.get("visuals", []) if isinstance(v, dict) and v.get("title") == self._selected_visual), None)
        if visual is None:
            return
        self._clipboard_format_config = {
            "color": visual.get("color", "#0078D4"),
            "show_data_labels": visual.get("show_data_labels", False),
            "show_legend": visual.get("show_legend", False),
        }
        self._format_painter_active = True
        self.stateChanged.emit()
        self._set_status("Format copied. Select another visual to apply it.")

    @Slot(str)
    def apply_format_painter(self, visual_title: str) -> None:
        if not self._format_painter_active or not self._clipboard_format_config:
            return
        page = self._active_page()
        for visual in page.get("visuals", []):
            if isinstance(visual, dict) and visual.get("title") == visual_title:
                for key, value in self._clipboard_format_config.items():
                    visual[key] = value
                self._dirty = True
                self._format_painter_active = False
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
        page = self._active_page()
        if page is None:
            return
        visuals = [item for item in page.get("visuals", []) if isinstance(item, dict)]
        selected = [
            item for item in visuals
            if str(item.get("id", "")) in self._selected_visual_ids
        ]
        selected_group_ids = {
            str(item["group_id"]) for item in selected if item.get("group_id")
        }
        if selected_group_ids:
            selected_ids = {str(item.get("id", "")) for item in selected}
            selected.extend(
                item for item in visuals
                if item.get("group_id") in selected_group_ids
                and str(item.get("id", "")) not in selected_ids
            )
        if len(selected) < 2:
            self._set_status("Select at least two visuals to group.")
            return
        group_id = str(uuid4())
        for visual in selected:
            visual["group_id"] = group_id
        self._dirty = True
        self.stateChanged.emit()
        self._set_status(f"Grouped {len(selected)} visuals")

    @Slot()
    def ungroup_visuals(self) -> None:
        page = self._active_page()
        if page is None:
            return
        visuals = [item for item in page.get("visuals", []) if isinstance(item, dict)]
        selected_group_ids = {
            str(item["group_id"])
            for item in visuals
            if str(item.get("id", "")) in self._selected_visual_ids
            and item.get("group_id")
        }
        if not selected_group_ids:
            self._set_status("Select a grouped visual to ungroup.")
            return
        for visual in visuals:
            if visual.get("group_id") in selected_group_ids:
                visual.pop("group_id", None)
        self._dirty = True
        self.stateChanged.emit()
        self._set_status("Ungrouped visuals")

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
