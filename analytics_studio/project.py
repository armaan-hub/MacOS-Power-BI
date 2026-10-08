"""Versioned, human-readable project files and crash-safe persistence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
from uuid import uuid4


FORMAT_ID = "com.analytics-studio.project"
FORMAT_VERSION = 68
SUPPORTED_VIEWS = {"Report", "Data", "Model"}
SUPPORTED_FILE_KINDS = {"csv", "excel", "json", "xml", "parquet", "sqlite"}
REPORT_FILTER_OPERATORS = {
    "equals", "not_equals", "contains", "does_not_contain",
    "begins_with", "does_not_begin_with", "ends_with", "does_not_end_with",
    "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
    "is_blank", "is_not_blank", "is_any_of", "is_none_of", "relative_date",
    "relative_time", "top_n",
}
REPORT_FILTER_MULTI_VALUE_OPERATORS = {"is_any_of", "is_none_of"}
REPORT_FILTER_RELATIVE_DATE_UNITS = {
    "days", "weeks", "calendar_weeks", "months", "calendar_months",
    "years", "calendar_years",
}
REPORT_FILTER_RELATIVE_TIME_UNITS = {"minutes", "hours"}
REPORT_FILTER_OPERATORS_WITHOUT_VALUE = {"is_blank", "is_not_blank"}
REPORT_FILTER_OPERATORS_REQUIRING_VALUE = REPORT_FILTER_OPERATORS - {
    "equals", "not_equals", "relative_date", "relative_time", "top_n",
    *REPORT_FILTER_OPERATORS_WITHOUT_VALUE,
}


class ProjectFileError(Exception):
    """A project file is unreadable or does not match its documented schema."""


class UnsupportedProjectVersion(ProjectFileError):
    """The project was written by a format version this app cannot read."""


def _validate_report_filters(filters: Any, *, scope_name: str, visual: bool = False) -> None:
    if not isinstance(filters, list) or len(filters) > 256:
        raise ProjectFileError(
            f"The {scope_name} filter collection must be a list of at most 256 filters."
        )
    field_keys: set[tuple[str, ...]] = set()
    required = {"table_id", "column", "clauses", "logic"}
    if visual:
        required.add("visual_name")
    for report_filter in filters:
        if not isinstance(report_filter, dict) or set(report_filter) != required:
            fields = ", ".join(sorted(required))
            raise ProjectFileError(
                f"Each {scope_name} filter must define only {fields}."
            )
        table_id = report_filter.get("table_id")
        column = report_filter.get("column")
        if not isinstance(table_id, str) or not table_id.strip():
            raise ProjectFileError(f"A {scope_name} filter needs a non-empty table_id.")
        if not isinstance(column, str) or not column.strip():
            raise ProjectFileError(f"A {scope_name} filter needs a non-empty column name.")
        visual_name = report_filter.get("visual_name") if visual else None
        if visual and (not isinstance(visual_name, str) or not visual_name.strip()):
            raise ProjectFileError("A visual filter needs a non-empty visual_name.")
        field_key = (visual_name, table_id, column) if visual else (table_id, column)
        if field_key in field_keys:
            raise ProjectFileError(
                f"A report {scope_name} filter collection cannot filter the same table column more than once."
            )
        field_keys.add(field_key)

        clauses = report_filter.get("clauses")
        if not isinstance(clauses, list) or not 1 <= len(clauses) <= 2:
            raise ProjectFileError(
                f"A {scope_name} filter needs one or two condition clauses."
        )
        has_relative_date = False
        has_relative_time = False
        has_top_n = False
        for clause in clauses:
            if not isinstance(clause, dict) or not isinstance(clause.get("operator"), str):
                raise ProjectFileError(f"A {scope_name} filter contains an invalid condition.")
            operator = clause["operator"]
            if operator not in REPORT_FILTER_OPERATORS:
                raise ProjectFileError(f"A {scope_name} filter contains an invalid condition.")
            if operator in REPORT_FILTER_MULTI_VALUE_OPERATORS:
                values = clause.get("values")
                if (
                    set(clause) != {"operator", "values"}
                    or not isinstance(values, list)
                    or not 1 <= len(values) <= 1000
                    or any(not isinstance(item, str) for item in values)
                    or len(set(values)) != len(values)
                ):
                    raise ProjectFileError(
                        f"The {operator} condition needs 1–1000 distinct text values."
                    )
                continue
            if operator == "relative_date":
                rule = clause
                if (
                    set(rule) != {
                        "operator", "direction", "count", "unit", "include_today"
                    }
                    or not isinstance(rule.get("direction"), str)
                    or rule["direction"] not in {"last", "this", "next"}
                    or type(rule.get("count")) is not int
                    or not 1 <= rule["count"] <= 1000
                    or (rule["direction"] == "this" and rule["count"] != 1)
                    or not isinstance(rule.get("unit"), str)
                    or rule["unit"] not in REPORT_FILTER_RELATIVE_DATE_UNITS
                    or not isinstance(rule.get("include_today"), bool)
                ):
                    raise ProjectFileError(
                        "A relative-date condition needs a direction, count, date unit, and include_today setting."
                    )
                has_relative_date = True
                continue
            if operator == "relative_time":
                rule = clause
                if (
                    set(rule) != {"operator", "direction", "count", "unit"}
                    or not isinstance(rule.get("direction"), str)
                    or rule["direction"] not in {"last", "this", "next"}
                    or type(rule.get("count")) is not int
                    or not 1 <= rule["count"] <= 1000
                    or (rule["direction"] == "this" and rule["count"] != 1)
                    or not isinstance(rule.get("unit"), str)
                    or rule["unit"] not in REPORT_FILTER_RELATIVE_TIME_UNITS
                ):
                    raise ProjectFileError(
                        "A relative-time condition needs a direction, count, and minute/hour unit."
                    )
                has_relative_time = True
                continue
            if operator == "top_n":
                rule = clause
                order_by = rule.get("order_by")
                if (
                    not visual
                    or set(rule) != {"operator", "direction", "count", "order_by"}
                    or not isinstance(rule.get("direction"), str)
                    or rule["direction"] not in {"top", "bottom"}
                    or type(rule.get("count")) is not int
                    or not 1 <= rule["count"] <= 1000
                    or not isinstance(order_by, dict)
                    or set(order_by) != {"table_id", "column"}
                    or not isinstance(order_by.get("table_id"), str)
                    or not order_by["table_id"].strip()
                    or not isinstance(order_by.get("column"), str)
                    or not order_by["column"].strip()
                ):
                    raise ProjectFileError(
                        "A Top N condition needs a visual scope, Top/Bottom, an item count, and an order-by field."
                    )
                has_top_n = True
                continue
            if set(clause) != {"operator", "value"} or not isinstance(clause.get("value"), str):
                raise ProjectFileError(f"A {scope_name} filter contains an invalid condition.")
            if (
                clause["operator"] in REPORT_FILTER_OPERATORS_WITHOUT_VALUE
                and clause["value"]
            ):
                raise ProjectFileError(
                    f"The {clause['operator']} condition does not take a comparison value."
                )
            if (
                clause["operator"] in REPORT_FILTER_OPERATORS_REQUIRING_VALUE
                and not clause["value"]
            ):
                raise ProjectFileError(
                    f"The {clause['operator']} condition needs a comparison value."
                )
        if has_relative_date and len(clauses) != 1:
            raise ProjectFileError("A relative-date filter must be the only condition for its field.")
        if has_relative_time and len(clauses) != 1:
            raise ProjectFileError("A relative-time filter must be the only condition for its field.")
        if has_top_n and len(clauses) != 1:
            raise ProjectFileError("A Top N filter must be the only condition for its field.")
        logic = report_filter.get("logic")
        if (
            not isinstance(logic, str)
            or logic not in {"and", "or"}
            or (len(clauses) == 1 and logic != "and")
        ):
            raise ProjectFileError(
                f"A {scope_name} filter condition join must be 'and' or 'or'."
            )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_project(name: str = "Untitled Project") -> dict[str, Any]:
    page_id = str(uuid4())
    now = utc_now()
    return {
        "format": FORMAT_ID,
        "format_version": FORMAT_VERSION,
        "project_id": str(uuid4()),
        "name": name,
        "created_at": now,
        "modified_at": now,
        "active_view": "Report",
        "active_source_id": None,
        "data_sources": [],
        "report": {
            "filters": [],
            "pages": [{
                "id": page_id,
                "name": "Overview",
                "visuals": [
                    {"id": str(uuid4()), "type": "card", "title": "Revenue KPI", "x": 14, "y": 14, "width": 120, "height": 80},
                    {"id": str(uuid4()), "type": "card", "title": "Cost KPI", "x": 148, "y": 14, "width": 120, "height": 80},
                    {"id": str(uuid4()), "type": "card", "title": "Margin KPI", "x": 282, "y": 14, "width": 120, "height": 80},
                    {"id": str(uuid4()), "type": "card", "title": "Units KPI", "x": 416, "y": 14, "width": 120, "height": 80},
                    {"id": str(uuid4()), "type": "card", "title": "Orders KPI", "x": 550, "y": 14, "width": 120, "height": 80},
                    {"id": str(uuid4()), "type": "column", "title": "Monthly revenue", "x": 14, "y": 108, "width": 330, "height": 248},
                    {"id": str(uuid4()), "type": "bar", "title": "Region revenue", "x": 358, "y": 108, "width": 330, "height": 248}
                ],
                "filters": [],
                "visual_filters": [],
            }],
            "active_page_id": page_id,
            "chart_types": {"monthly": "column", "region": "bar"},
        },
        "model": {"tables": [], "relationships": [], "measures": []},
    }


def validate_project(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectFileError("The project root must be a JSON object.")
    if value.get("format") != FORMAT_ID:
        raise ProjectFileError("This file is not an Analytics Studio project.")

    version = value.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProjectFileError("The project has no valid format_version.")
    if version > FORMAT_VERSION:
        raise UnsupportedProjectVersion(
            f"This project uses format version {version}; this app supports up to {FORMAT_VERSION}."
        )
    if version < 1:
        raise UnsupportedProjectVersion(f"Project format version {version} is not supported.")
    value = deepcopy(value)
    while version < FORMAT_VERSION:
        if version == 1:
            value = _migrate_v1_to_v2(value)
        elif version == 2:
            value = _migrate_v2_to_v3(value)
        elif version == 3:
            value = _migrate_v3_to_v4(value)
        elif version == 4:
            value = _migrate_v4_to_v5(value)
        elif version == 5:
            value = _migrate_v5_to_v6(value)
        elif version == 6:
            value = _migrate_v6_to_v7(value)
        elif version == 7:
            value = _migrate_v7_to_v8(value)
        elif version == 8:
            value = _migrate_v8_to_v9(value)
        elif version == 9:
            value = _migrate_v9_to_v10(value)
        elif version == 10:
            value = _migrate_v10_to_v11(value)
        elif version == 11:
            value = _migrate_v11_to_v12(value)
        elif version == 12:
            value = _migrate_v12_to_v13(value)
        elif version == 13:
            value = _migrate_v13_to_v14(value)
        elif version == 14:
            value = _migrate_v14_to_v15(value)
        elif version == 15:
            value = _migrate_v15_to_v16(value)
        elif version == 16:
            value = _migrate_v16_to_v17(value)
        elif version == 17:
            value = _migrate_v17_to_v18(value)
        elif version == 18:
            value = _migrate_v18_to_v19(value)
        elif version == 19:
            value = _migrate_v19_to_v20(value)
        elif version == 20:
            value = _migrate_v20_to_v21(value)
        elif version == 21:
            value = _migrate_v21_to_v22(value)
        elif version == 22:
            value = _migrate_v22_to_v23(value)
        elif version == 23:
            value = _migrate_v23_to_v24(value)
        elif version == 24:
            value = _migrate_v24_to_v25(value)
        elif version == 25:
            value = _migrate_v25_to_v26(value)
        elif version == 26:
            value = _migrate_v26_to_v27(value)
        elif version == 27:
            value = _migrate_v27_to_v28(value)
        elif version == 28:
            value = _migrate_v28_to_v29(value)
        elif version == 29:
            value = _migrate_v29_to_v30(value)
        elif version == 30:
            value = _migrate_v30_to_v31(value)
        elif version == 31:
            value = _migrate_v31_to_v32(value)
        elif version == 32:
            value = _migrate_v32_to_v33(value)
        elif version == 33:
            value = _migrate_v33_to_v34(value)
        elif version == 34:
            value = _migrate_v34_to_v35(value)
        elif version == 35:
            value = _migrate_v35_to_v36(value)
        elif version == 36:
            value = _migrate_v36_to_v37(value)
        elif version == 37:
            value = _migrate_v37_to_v38(value)
        elif version == 38:
            value = _migrate_v38_to_v39(value)
        elif version == 39:
            value = _migrate_v39_to_v40(value)
        elif version == 40:
            value = _migrate_v40_to_v41(value)
        elif version == 41:
            value = _migrate_v41_to_v42(value)
        elif version == 42:
            value = _migrate_v42_to_v43(value)
        elif version == 43:
            value = _migrate_v43_to_v44(value)
        elif version == 44:
            value = _migrate_v44_to_v45(value)
        elif version == 45:
            value = _migrate_v45_to_v46(value)
        elif version == 46:
            value = _migrate_v46_to_v47(value)
        elif version == 47:
            value = _migrate_v47_to_v48(value)
        elif version == 48:
            value = _migrate_v48_to_v49(value)
        elif version == 49:
            value = _migrate_v49_to_v50(value)
        elif version == 50:
            value = _migrate_v50_to_v51(value)
        elif version == 51:
            value = _migrate_v51_to_v52(value)
        elif version == 52:
            value = _migrate_v52_to_v53(value)
        elif version == 53:
            value = _migrate_v53_to_v54(value)
        elif version == 54:
            value = _migrate_v54_to_v55(value)
        elif version == 55:
            value = _migrate_v55_to_v56(value)
        elif version == 56:
            value = _migrate_v56_to_v57(value)
        elif version == 57:
            value = _migrate_v57_to_v58(value)
        elif version == 58:
            value = _migrate_v58_to_v59(value)
        elif version == 59:
            value = _migrate_v59_to_v60(value)
        elif version == 60:
            value = _migrate_v60_to_v61(value)
        elif version == 61:
            value = _migrate_v61_to_v62(value)
        elif version == 62:
            value = _migrate_v62_to_v63(value)
        elif version == 63:
            value = _migrate_v63_to_v64(value)
        elif version == 64:
            value = _migrate_v64_to_v65(value)
        elif version == 65:
            value = _migrate_v65_to_v66(value)
        elif version == 66:
            value = _migrate_v66_to_v67(value)
        elif version == 67:
            value = _migrate_v67_to_v68(value)
        else:
            raise UnsupportedProjectVersion(f"Project format version {version} is not supported.")
        version = value.get("format_version")
    if version != FORMAT_VERSION:
        raise UnsupportedProjectVersion(f"Project format version {version} is not supported.")

    for key in ("project_id", "name", "created_at", "modified_at"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ProjectFileError(f"The project field {key!r} must be a non-empty string.")
    active_view = value.get("active_view")
    if not isinstance(active_view, str) or active_view not in SUPPORTED_VIEWS:
        raise ProjectFileError("The project active_view must be Report, Data, or Model.")

    sources = value.get("data_sources")
    if not isinstance(sources, list):
        raise ProjectFileError("The project data_sources field must be a list.")
    source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ProjectFileError("Each data source must be a JSON object.")
        for key in ("id", "name", "kind"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ProjectFileError(f"Each data source needs a non-empty {key!r} field.")
        if source["id"] in source_ids:
            raise ProjectFileError(f"Data source ID {source['id']!r} is duplicated.")
        source_ids.add(source["id"])
        if any(key.casefold() in {"password", "pwd", "connection_string"} for key in source):
            raise ProjectFileError("Data source credentials must not be stored in the project file.")
        if "query_group" in source:
            query_group = source["query_group"]
            if (
                not isinstance(query_group, str)
                or not query_group.strip()
                or len(query_group.strip()) > 80
                or any(ord(char) < 32 for char in query_group)
            ):
                raise ProjectFileError(
                    "A query_group must be a non-empty name of at most 80 characters."
                )
            source["query_group"] = query_group.strip()
        if source["kind"] == "inline":
            if "path" in source:
                raise ProjectFileError("An inline data source must not contain a file path.")
            if "parser_options" in source:
                raise ProjectFileError("An inline data source must not contain file parser_options.")
            from analytics_studio.inline_data import InlineDataError, normalize_inline_data

            try:
                source["headers"], source["rows"] = normalize_inline_data(
                    source.get("headers"), source.get("rows")
                )
            except InlineDataError as exc:
                raise ProjectFileError(f"The inline data source {source['id']!r} is invalid: {exc}") from exc
        elif source["kind"] == "query":
            if any(key in source for key in ("path", "parser_options", "headers", "rows")):
                raise ProjectFileError(
                    "A query source must not contain file paths, parser options, or inline rows."
                )
            if not isinstance(source.get("load_enabled", True), bool):
                raise ProjectFileError("A query source load_enabled setting must be true or false.")
            source["load_enabled"] = source.get("load_enabled", True)
            if not isinstance(source.get("include_in_report_refresh", True), bool):
                raise ProjectFileError(
                    "A query source include_in_report_refresh setting must be true or false."
                )
            source["include_in_report_refresh"] = source.get(
                "include_in_report_refresh", True
            )
        elif source["kind"] == "odata":
            if "path" in source:
                raise ProjectFileError("An OData data source must not contain a file path.")
            from analytics_studio.odata import ODataError, validate_odata_source

            try:
                source["connection"], source["parser_options"] = validate_odata_source(
                    source.get("connection"), source.get("parser_options")
                )
            except ODataError as exc:
                raise ProjectFileError(f"The OData source {source['id']!r} is invalid: {exc}") from exc
        elif source["kind"] == "web":
            if "path" in source:
                raise ProjectFileError("A Web data source must not contain a file path.")
            from analytics_studio.web_import import WebImportError, validate_web_source

            try:
                source["connection"], source["parser_options"] = validate_web_source(
                    source.get("connection"), source.get("parser_options")
                )
            except WebImportError as exc:
                raise ProjectFileError(f"The Web source {source['id']!r} is invalid: {exc}") from exc
        elif source["kind"] == "sql_server":
            if "path" in source:
                raise ProjectFileError("A SQL Server data source must not contain a file path.")
            connection = source.get("connection")
            expected_connection_keys = {
                "server", "port", "database", "username", "driver", "encrypt", "credential_ref",
            }
            if not isinstance(connection, dict) or set(connection) != expected_connection_keys:
                raise ProjectFileError(f"The SQL Server connection for {source['id']!r} is invalid.")
            from analytics_studio.sql_server import SUPPORTED_DRIVERS

            server = connection.get("server")
            if (
                not isinstance(server, str)
                or not server.strip()
                or len(server) > 255
                or any(ord(char) < 32 for char in server)
                or not all(char.isalnum() or char in "_.:%[]-" for char in server)
            ):
                raise ProjectFileError("A SQL Server source needs a valid host name or IP address.")
            for field, maximum in (("database", 128), ("username", 128)):
                text = connection.get(field)
                if (
                    not isinstance(text, str)
                    or not text.strip()
                    or len(text) > maximum
                    or any(ord(char) < 32 for char in text)
                ):
                    raise ProjectFileError(f"A SQL Server source needs a valid {field}.")
            port = connection.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                raise ProjectFileError("A SQL Server source port must be between 1 and 65535.")
            if connection.get("driver") not in SUPPORTED_DRIVERS:
                raise ProjectFileError("A SQL Server source has an unsupported ODBC driver.")
            if connection.get("encrypt") is not True:
                raise ProjectFileError("SQL Server connections must use encryption.")
            credential_ref = connection.get("credential_ref")
            if not isinstance(credential_ref, str) or not credential_ref.strip() or len(credential_ref) > 80:
                raise ProjectFileError("A SQL Server source needs a Keychain credential reference.")
            object_options = source.get("parser_options")
            if not isinstance(object_options, dict) or set(object_options) != {
                "schema", "table_name", "object_type",
            }:
                raise ProjectFileError("A SQL Server source needs a selected schema and table name.")
            for field in ("schema", "table_name"):
                text = object_options.get(field)
                if (
                    not isinstance(text, str)
                    or not text.strip()
                    or len(text) > 128
                    or any(ord(char) < 32 for char in text)
                ):
                    raise ProjectFileError(f"A SQL Server source needs a valid {field}.")
            if object_options.get("object_type") not in {"TABLE", "VIEW"}:
                raise ProjectFileError("A SQL Server source has an unsupported selected object type.")
        else:
            if not isinstance(source.get("path"), str) or not source["path"].strip():
                raise ProjectFileError("Each file data source needs a non-empty 'path' field.")
            if "\x00" in source["path"]:
                raise ProjectFileError("A data source path contains an invalid character.")

    from analytics_studio.query_engine import JOIN_KINDS

    query_dependencies: dict[str, list[str]] = {}
    for source in sources:
        if source.get("kind") != "query":
            continue
        definition = source.get("query_definition")
        if not isinstance(definition, dict):
            raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
        operation = definition.get("operation")
        if operation == "append":
            if set(definition) != {"operation", "source_ids"}:
                raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
            minimum_dependencies = 2
            maximum_dependencies = None
        elif operation == "merge":
            if set(definition) != {
                "operation", "source_ids", "left_keys", "right_keys", "join_kind", "right_name",
            }:
                raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
            minimum_dependencies = 2
            maximum_dependencies = 2
            left_keys = definition.get("left_keys")
            right_keys = definition.get("right_keys")
            if (
                not isinstance(left_keys, list)
                or not isinstance(right_keys, list)
                or not left_keys
                or len(left_keys) != len(right_keys)
                or any(not isinstance(item, str) or not item.strip() for item in left_keys + right_keys)
                or len(set(left_keys)) != len(left_keys)
                or len(set(right_keys)) != len(right_keys)
            ):
                raise ProjectFileError("A merge query needs unique, paired key column names.")
            if (
                not isinstance(definition.get("join_kind"), str)
                or definition.get("join_kind") not in JOIN_KINDS
            ):
                raise ProjectFileError("A merge query has an unsupported join kind.")
            right_name = definition.get("right_name")
            if not isinstance(right_name, str) or not right_name.strip():
                raise ProjectFileError("A merge query needs a right table name for its output columns.")
        elif operation == "calculated_table":
            if set(definition) != {
                "operation", "source_ids", "expression", "source_table",
            }:
                raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
            minimum_dependencies = 1
            maximum_dependencies = 1
            source_table = definition.get("source_table")
            from analytics_studio.measures import (
                MeasureError,
                normalize_calculated_table_expression,
            )

            try:
                calculated_table_definition = normalize_calculated_table_expression(
                    definition.get("expression"), source_table
                )
            except MeasureError as exc:
                raise ProjectFileError(
                    f"The calculated table {source['id']!r} is invalid: {exc}"
                ) from exc
        elif operation == "calendar":
            if set(definition) != {
                "operation", "source_ids", "start_date", "end_date",
            }:
                raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
            minimum_dependencies = 0
            maximum_dependencies = 0
            from analytics_studio.calendar_tables import (
                CalendarTableError,
                parse_calendar_date,
                validate_calendar_range,
            )

            try:
                start_date = parse_calendar_date(
                    definition.get("start_date"), label="The calendar start date"
                )
                end_date = parse_calendar_date(
                    definition.get("end_date"), label="The calendar end date"
                )
                validate_calendar_range(start_date, end_date)
            except CalendarTableError as exc:
                raise ProjectFileError(
                    f"The calendar table {source['id']!r} is invalid: {exc}"
                ) from exc
        elif operation == "calendar_auto":
            if set(definition) != {
                "operation", "source_ids", "fiscal_year_end_month",
            }:
                raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
            minimum_dependencies = 0
            maximum_dependencies = None
            fiscal_year_end_month = definition.get("fiscal_year_end_month")
            if (
                not isinstance(fiscal_year_end_month, int)
                or isinstance(fiscal_year_end_month, bool)
                or not 1 <= fiscal_year_end_month <= 12
            ):
                raise ProjectFileError(
                    "A CALENDARAUTO query fiscal year end month must be between 1 and 12."
                )
        else:
            raise ProjectFileError(f"The query_definition for {source['id']!r} is invalid.")
        dependencies = definition.get("source_ids")
        if (
            not isinstance(dependencies, list)
            or len(dependencies) < minimum_dependencies
            or (maximum_dependencies is not None and len(dependencies) != maximum_dependencies)
            or any(not isinstance(item, str) or not item.strip() for item in dependencies)
            or len(set(dependencies)) != len(dependencies)
        ):
            raise ProjectFileError("A query needs the required number of unique source IDs.")
        if operation == "calendar_auto":
            # CALENDARAUTO dependencies are canonicalized after all query
            # definitions are known, so later-added tables enter the scan.
            dependencies = []
        if source["id"] in dependencies:
            raise ProjectFileError("A query cannot depend on itself.")
        missing = next((item for item in dependencies if item not in source_ids), None)
        if missing is not None:
            raise ProjectFileError(f"Query source {missing!r} does not exist in this project.")
        query_dependencies[source["id"]] = list(dependencies)
        if operation == "append":
            source["query_definition"] = {
                "operation": "append",
                "source_ids": list(dependencies),
            }
        elif operation == "merge":
            source["query_definition"] = {
                "operation": "merge",
                "source_ids": list(dependencies),
                "left_keys": list(left_keys),
                "right_keys": list(right_keys),
                "join_kind": definition["join_kind"],
                "right_name": right_name.strip(),
            }
        else:
            if operation == "calculated_table":
                dependency = next(item for item in sources if item["id"] == dependencies[0])
                project_model = value.get("model", {})
                model_tables = project_model.get("tables", []) if isinstance(project_model, dict) else []
                dependency_table = next((
                    table for table in model_tables
                    if isinstance(table, dict)
                    and (table.get("source_id") == dependencies[0] or table.get("id") == dependencies[0])
                ), None)
                expected_table_name = str(
                    dependency_table.get("name") if dependency_table else dependency["name"]
                )
                if expected_table_name.casefold() != source_table.strip().casefold():
                    raise ProjectFileError(
                        "A calculated-table expression must reference its saved source table."
                    )
                source["query_definition"] = {
                    "operation": "calculated_table",
                    "source_ids": list(dependencies),
                    "expression": calculated_table_definition["expression"],
                    "source_table": expected_table_name,
                }
            elif operation == "calendar":
                source["query_definition"] = {
                    "operation": "calendar",
                    "source_ids": [],
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                }
            else:
                source["query_definition"] = {
                    "operation": "calendar_auto",
                    "source_ids": list(dependencies),
                    "fiscal_year_end_month": fiscal_year_end_month,
                }

    project_model = value.get("model", {})
    model_tables = project_model.get("tables", []) if isinstance(project_model, dict) else []
    model_table_ids = {
        str(table.get("source_id") or table.get("id"))
        for table in model_tables if isinstance(table, dict)
    }
    sources_by_id = {str(source["id"]): source for source in sources}

    def derives_from_generated_date_table(source_id: str, visited_ids: set[str]) -> bool:
        if source_id in visited_ids:
            return False
        next_visited_ids = visited_ids | {source_id}
        candidate_source = sources_by_id.get(source_id)
        if candidate_source is None or candidate_source.get("kind") != "query":
            return False
        query_definition = candidate_source.get("query_definition", {})
        query_operation = query_definition.get("operation")
        if query_operation in {"calculated_table", "calendar", "calendar_auto"}:
            return True
        if query_operation in {"append", "merge"}:
            return any(
                derives_from_generated_date_table(str(dependency), next_visited_ids)
                for dependency in query_definition.get("source_ids", [])
            )
        return False

    for source in sources:
        definition = source.get("query_definition", {}) if source.get("kind") == "query" else {}
        if definition.get("operation") != "calendar_auto":
            continue
        auto_dependencies = []
        for candidate_source in sources:
            candidate_id = str(candidate_source["id"])
            if candidate_id == str(source["id"]) or candidate_id not in model_table_ids:
                continue
            if candidate_source.get("kind") != "query":
                auto_dependencies.append(candidate_id)
                continue
            query_operation = candidate_source.get("query_definition", {}).get("operation")
            if (
                candidate_source.get("load_enabled", True) is True
                and query_operation in {"append", "merge"}
                and not derives_from_generated_date_table(candidate_id, set())
            ):
                auto_dependencies.append(candidate_id)
        definition["source_ids"] = auto_dependencies
        query_dependencies[str(source["id"])] = auto_dependencies

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_query(source_id: str) -> None:
        if source_id in visited:
            return
        if source_id in visiting:
            raise ProjectFileError("Query dependencies contain a cycle.")
        visiting.add(source_id)
        for dependency in query_dependencies.get(source_id, []):
            visit_query(dependency)
        visiting.remove(source_id)
        visited.add(source_id)

    for source_id in query_dependencies:
        visit_query(source_id)

    active_source_id = value.get("active_source_id")
    if active_source_id is not None and (
        not isinstance(active_source_id, str)
        or not active_source_id.strip()
        or not any(source.get("id") == active_source_id for source in sources)
    ):
        raise ProjectFileError("The active_source_id must be null or match an existing data source.")

    # Add defaults for early v2 documents that omit options. Validate and canonicalize
    # persisted settings so refresh and reopen interpret the source consistently.
    from analytics_studio.file_import import default_options, normalize_options

    for source in sources:
        if source.get("kind") == "folder":
            from analytics_studio.folder_import import normalize_folder_options

            try:
                source["parser_options"] = normalize_folder_options(
                    source.get("parser_options", {})
                )
            except (TypeError, ValueError) as exc:
                raise ProjectFileError(
                    f"The parser_options for folder source {source['id']!r} are invalid: {exc}"
                ) from exc
            continue
        if source.get("kind") not in SUPPORTED_FILE_KINDS:
            continue
        options = source.get("parser_options", default_options(source["kind"]))
        try:
            source["parser_options"] = normalize_options(source["kind"], options)
        except (TypeError, ValueError) as exc:
            raise ProjectFileError(
                f"The parser_options for data source {source['id']!r} are invalid: {exc}"
            ) from exc

    from analytics_studio.transformations import (
        SUPPORTED_COLUMN_TYPES,
        TransformationError,
        canonical_column_type,
        validate_steps,
    )

    for source in sources:
        try:
            source["transform_steps"] = validate_steps(source.get("transform_steps", []))
        except TransformationError as exc:
            raise ProjectFileError(
                f"The transform_steps for data source {source['id']!r} are invalid: {exc}"
            ) from exc

    report = value.get("report")
    pages = report.get("pages") if isinstance(report, dict) else None
    if not isinstance(pages, list) or not pages:
        raise ProjectFileError("A project must contain at least one report page.")
    _validate_report_filters(report.get("filters"), scope_name="report")
    page_ids: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise ProjectFileError("Each report page must be a JSON object.")
        page_id = page.get("id")
        if not isinstance(page_id, str) or not page_id.strip() or page_id in page_ids:
            raise ProjectFileError("Report page IDs must be non-empty and unique.")
        page_ids.add(page_id)
        if not isinstance(page.get("name"), str) or not page["name"].strip():
            raise ProjectFileError("Each report page needs a non-empty name.")
        visuals = page.get("visuals")
        if not isinstance(visuals, list):
            raise ProjectFileError("A report page visuals field must be a list.")
        visual_ids = set()
        for visual in visuals:
            if not isinstance(visual, dict):
                raise ProjectFileError("Each report visual must be a dictionary.")
            v_id = visual.get("id")
            if not isinstance(v_id, str) or not v_id:
                raise ProjectFileError("Report visuals must have unique id strings.")
            if v_id in visual_ids:
                raise ProjectFileError("Report visuals must have unique id strings.")
            visual_ids.add(v_id)
            if not isinstance(visual.get("title", ""), str):
                raise ProjectFileError("Report visual title must be a string.")
            if not isinstance(visual.get("type"), str):
                raise ProjectFileError("Report visual type must be a string.")
            for key in ("x", "y", "width", "height"):
                if key in visual and not isinstance(visual[key], (int, float)):
                    raise ProjectFileError(f"Report visual '{key}' must be a number.")
        hidden = page.get("hidden", False)
        if type(hidden) is not bool:
            raise ProjectFileError("A report page hidden field must be a boolean.")
        page["hidden"] = hidden
        _validate_report_filters(page.get("filters"), scope_name="page")
        _validate_report_filters(page.get("visual_filters"), scope_name="visual", visual=True)
    active_page_id = report.get("active_page_id")
    if not isinstance(active_page_id, str) or active_page_id not in page_ids:
        raise ProjectFileError("The report active_page_id must match an existing page.")
    chart_types = report.get("chart_types")
    if (
        not isinstance(chart_types, dict)
        or not isinstance(chart_types.get("monthly"), str)
        or chart_types.get("monthly") not in {"column", "bar", "line"}
        or not isinstance(chart_types.get("region"), str)
        or chart_types.get("region") not in {"column", "bar", "line"}
    ):
        raise ProjectFileError("The report chart_types must define monthly and region chart types.")

    model = value.get("model")
    if not isinstance(model, dict):
        raise ProjectFileError("The project model field must be an object.")
    model.setdefault("measures", [])
    for key in ("tables", "relationships"):
        if not isinstance(model.get(key), list):
            raise ProjectFileError(f"The project model {key!r} field must be a list.")
    for table in model["tables"]:
        if not isinstance(table, dict) or not isinstance(table.get("name"), str):
            raise ProjectFileError("Each model table must have a name.")
        table.setdefault("calculated_columns", [])
        column_types = table.get("column_types", {})
        if not isinstance(column_types, dict):
            raise ProjectFileError("Each model table column_types field must be an object.")
        normalized_types: dict[str, str] = {}
        for column, type_name in column_types.items():
            if not isinstance(column, str) or not column.strip() or not isinstance(type_name, str):
                raise ProjectFileError("Model column types need non-empty column names and type names.")
            canonical_type = canonical_column_type(type_name)
            if canonical_type not in SUPPORTED_COLUMN_TYPES:
                raise ProjectFileError(f"Unsupported model column type {type_name!r}.")
            normalized_types[column] = canonical_type
        table["column_types"] = normalized_types
        date_column = table.get("date_column")
        if date_column is not None:
            if not isinstance(date_column, str) or not date_column.strip():
                raise ProjectFileError("A model date_column must be a non-empty column name or null.")
            date_column = date_column.strip()
            if normalized_types.get(date_column) not in {"date", "datetime"}:
                raise ProjectFileError(
                    f"The marked date column {date_column!r} must have the date or datetime model type."
                )
            table["date_column"] = date_column
        else:
            table["date_column"] = None
        from analytics_studio.measures import MeasureError, validate_calculated_columns

        try:
            table["calculated_columns"] = validate_calculated_columns(
                table["calculated_columns"]
            )
        except MeasureError as exc:
            raise ProjectFileError(
                f"The calculated columns for table {table['name']!r} are invalid: {exc}"
            ) from exc
    from analytics_studio.relationships import RelationshipError, normalize_relationships

    try:
        model["relationships"] = normalize_relationships(
            model["relationships"], model["tables"]
        )
    except RelationshipError as exc:
        raise ProjectFileError(f"The project model relationships are invalid: {exc}") from exc

    from analytics_studio.measures import MeasureError, validate_measures

    try:
        model["measures"] = validate_measures(model["measures"])
    except MeasureError as exc:
        raise ProjectFileError(f"The project model measures are invalid: {exc}") from exc

    return deepcopy(value)


def _migrate_v1_to_v2(value: dict[str, Any]) -> dict[str, Any]:
    """Convert v1 in memory, preserving its first CSV/Excel source selection rule."""
    from analytics_studio.file_import import default_options

    migrated = deepcopy(value)
    sources = migrated.get("data_sources")
    if not isinstance(sources, list):
        sources = []
    active = next(
        (source for source in sources
         if isinstance(source, dict) and source.get("kind") in {"csv", "excel"}),
        None,
    )
    migrated["active_source_id"] = active.get("id") if active else None
    for source in sources:
        if isinstance(source, dict) and source.get("kind") in SUPPORTED_FILE_KINDS:
            source.setdefault("parser_options", default_options(source["kind"]))
    migrated["format_version"] = 2
    return migrated


def _migrate_v2_to_v3(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v2 documents to the schema that can store inline table rows."""
    migrated = deepcopy(value)
    migrated["format_version"] = 3
    return migrated


def _migrate_v3_to_v4(value: dict[str, Any]) -> dict[str, Any]:
    """Add an empty transformation pipeline to v3 file and inline sources."""
    migrated = deepcopy(value)
    for source in migrated.get("data_sources", []):
        if isinstance(source, dict):
            source.setdefault("transform_steps", [])
    migrated["format_version"] = 4
    return migrated


def _migrate_v4_to_v5(value: dict[str, Any]) -> dict[str, Any]:
    """Add local calculated measures without changing any existing model state."""
    migrated = deepcopy(value)
    model = migrated.setdefault("model", {})
    if isinstance(model, dict):
        model.setdefault("measures", [])
    migrated["format_version"] = 5
    return migrated


def _migrate_v5_to_v6(value: dict[str, Any]) -> dict[str, Any]:
    """Add persistent column type metadata to model tables."""
    migrated = deepcopy(value)
    model = migrated.setdefault("model", {})
    if isinstance(model, dict):
        tables = model.setdefault("tables", [])
        if isinstance(tables, list):
            for table in tables:
                if isinstance(table, dict):
                    table.setdefault("column_types", {})
    migrated["format_version"] = 6
    return migrated


def _migrate_v6_to_v7(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v6 projects to the schema that stores derived query sources."""
    migrated = deepcopy(value)
    migrated["format_version"] = 7
    return migrated


def _migrate_v7_to_v8(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v7 projects to the schema that also stores merge queries."""
    migrated = deepcopy(value)
    migrated["format_version"] = 8
    return migrated


def _migrate_v8_to_v9(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v8 projects to the schema that stores query group names."""
    migrated = deepcopy(value)
    migrated["format_version"] = 9
    return migrated


def _migrate_v9_to_v10(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v9 projects to the schema that supports delimiter split steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 10
    return migrated


def _migrate_v10_to_v11(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v10 projects to the schema that supports split-to-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 11
    return migrated


def _migrate_v11_to_v12(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v11 projects to the schema that supports group-by steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 12
    return migrated


def _migrate_v12_to_v13(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v12 projects to the schema that supports unpivot steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 13
    return migrated


def _migrate_v13_to_v14(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v13 projects to the schema that supports pivot steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 14
    return migrated


def _migrate_v14_to_v15(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v14 projects to the schema that supports custom-column steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 15
    return migrated


def _migrate_v15_to_v16(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v15 projects to the schema that supports conditional-column steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 16
    return migrated


def _migrate_v16_to_v17(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v16 projects to the schema that supports merge-column steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 17
    return migrated


def _migrate_v17_to_v18(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v17 projects to the schema that supports fill-down/up steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 18
    return migrated


def _migrate_v18_to_v19(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v18 projects to the schema that supports duplicate-column steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 19
    return migrated


def _migrate_v19_to_v20(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v19 projects to query load settings, enabled by default."""
    migrated = deepcopy(value)
    for source in migrated.get("data_sources", []):
        if source.get("kind") == "query":
            source.setdefault("load_enabled", True)
    migrated["format_version"] = 20
    return migrated


def _migrate_v20_to_v21(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v20 projects to saved query refresh settings, enabled by default."""
    migrated = deepcopy(value)
    for source in migrated.get("data_sources", []):
        if source.get("kind") == "query":
            source.setdefault("include_in_report_refresh", True)
    migrated["format_version"] = 21
    return migrated


def _migrate_v21_to_v22(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v21 projects to the schema that supports blank-row steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 22
    return migrated


def _migrate_v22_to_v23(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v22 projects to the schema that supports remove-top-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 23
    return migrated


def _migrate_v23_to_v24(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v23 projects to the schema that supports remove-bottom-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 24
    return migrated


def _migrate_v24_to_v25(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v24 projects to the schema that supports keep-top-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 25
    return migrated


def _migrate_v25_to_v26(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v25 projects to the schema that supports keep-bottom-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 26
    return migrated


def _migrate_v26_to_v27(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v26 projects to the schema that supports keep-range-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 27
    return migrated


def _migrate_v27_to_v28(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v27 projects to the schema that supports remove-alternate-rows steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 28
    return migrated


def _migrate_v28_to_v29(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v28 projects to the schema that supports add-index-column steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 29
    return migrated


def _migrate_v29_to_v30(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v29 projects to the schema that supports reorder-column steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 30
    return migrated


def _migrate_v30_to_v31(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v30 projects to the schema that supports promote-header steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 31
    return migrated


def _migrate_v31_to_v32(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v31 projects to the schema that supports demote-header steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 32
    return migrated


def _migrate_v32_to_v33(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v32 projects to the schema that supports clean-text steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 33
    return migrated


def _migrate_v33_to_v34(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v33 projects to the schema that supports lowercase-text steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 34
    return migrated


def _migrate_v34_to_v35(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v34 projects to the schema that supports uppercase-text steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 35
    return migrated


def _migrate_v35_to_v36(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v35 projects to the schema that supports locale-aware type steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 36
    return migrated


def _migrate_v36_to_v37(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v36 projects to the schema that supports table transposition."""
    migrated = deepcopy(value)
    migrated["format_version"] = 37
    return migrated


def _migrate_v37_to_v38(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v37 projects to the schema that supports positional split steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 38
    return migrated


def _migrate_v38_to_v39(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v38 projects to the schema that supports every-delimiter splits."""
    migrated = deepcopy(value)
    migrated["format_version"] = 39
    return migrated


def _migrate_v39_to_v40(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v39 projects to the schema that supports delimiter extraction."""
    migrated = deepcopy(value)
    migrated["format_version"] = 40
    return migrated


def _migrate_v40_to_v41(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v40 projects to the schema that supports between-delimiter extraction."""
    migrated = deepcopy(value)
    migrated["format_version"] = 41
    return migrated


def _migrate_v41_to_v42(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v41 projects to the schema that supports proper-case text steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 42
    return migrated


def _migrate_v42_to_v43(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v42 projects to the schema that supports reverse-text steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 43
    return migrated


def _migrate_v43_to_v44(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v43 projects to selected-column duplicate-removal steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 44
    return migrated


def _migrate_v44_to_v45(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v44 projects to keep-duplicates steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 45
    return migrated


def _migrate_v45_to_v46(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v45 projects to multiple-column sort steps."""
    migrated = deepcopy(value)
    migrated["format_version"] = 46
    return migrated


def _migrate_v46_to_v47(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v46 projects to the expanded text-filter operators."""
    migrated = deepcopy(value)
    migrated["format_version"] = 47
    return migrated


def _migrate_v47_to_v48(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v47 projects to inclusive numeric row-filter operators."""
    migrated = deepcopy(value)
    migrated["format_version"] = 48
    return migrated


def _migrate_v48_to_v49(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v48 projects to advanced multi-column row filters."""
    migrated = deepcopy(value)
    migrated["format_version"] = 49
    return migrated


def _migrate_v49_to_v50(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v49 projects to blank/nonblank row filters."""
    migrated = deepcopy(value)
    migrated["format_version"] = 50
    return migrated


def _migrate_v50_to_v51(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v50 projects to the local SQLite source format."""
    migrated = deepcopy(value)
    migrated["format_version"] = 51
    return migrated


def _migrate_v51_to_v52(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v51 projects to the SQL Server linked-source schema."""
    migrated = deepcopy(value)
    migrated["format_version"] = 52
    return migrated


def _migrate_v52_to_v53(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v52 projects to the pathless OData Feed source schema."""
    migrated = deepcopy(value)
    migrated["format_version"] = 53
    return migrated


def _migrate_v53_to_v54(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v53 projects to the pathless Web source schema."""
    migrated = deepcopy(value)
    migrated["format_version"] = 54
    return migrated


def _migrate_v54_to_v55(value: dict[str, Any]) -> dict[str, Any]:
    """Add saved, page-scoped filter collections."""
    migrated = deepcopy(value)
    report = migrated.get("report", {})
    pages = report.get("pages", []) if isinstance(report, dict) else []
    for page in pages:
        if isinstance(page, dict):
            page.setdefault("filters", [])
    migrated["format_version"] = 55
    return migrated


def _migrate_v55_to_v56(value: dict[str, Any]) -> dict[str, Any]:
    """Add saved visual-scoped filter collections."""
    migrated = deepcopy(value)
    report = migrated.get("report", {})
    pages = report.get("pages", []) if isinstance(report, dict) else []
    for page in pages:
        if isinstance(page, dict):
            page.setdefault("visual_filters", [])
    migrated["format_version"] = 56
    return migrated


def _migrate_v56_to_v57(value: dict[str, Any]) -> dict[str, Any]:
    """Store report filters as one or two typed condition clauses."""
    migrated = deepcopy(value)
    report = migrated.get("report", {})
    pages = report.get("pages", []) if isinstance(report, dict) else []
    for page in pages:
        if not isinstance(page, dict):
            continue
        for collection_name in ("filters", "visual_filters"):
            filters = page.get(collection_name, [])
            if not isinstance(filters, list):
                continue
            for report_filter in filters:
                if not isinstance(report_filter, dict) or "clauses" in report_filter:
                    continue
                value_text = report_filter.pop("value", "")
                report_filter["clauses"] = [{"operator": "equals", "value": value_text}]
                report_filter["logic"] = "and"
    migrated["format_version"] = 57
    return migrated


def _migrate_v57_to_v58(value: dict[str, Any]) -> dict[str, Any]:
    """Enable multi-value report-filter conditions without changing existing filters."""
    migrated = deepcopy(value)
    migrated["format_version"] = 58
    return migrated


def _migrate_v58_to_v59(value: dict[str, Any]) -> dict[str, Any]:
    """Enable relative-date report-filter clauses without changing existing filters."""
    migrated = deepcopy(value)
    migrated["format_version"] = 59
    return migrated


def _migrate_v59_to_v60(value: dict[str, Any]) -> dict[str, Any]:
    """Enable relative-time report-filter clauses without changing existing filters."""
    migrated = deepcopy(value)
    migrated["format_version"] = 60
    return migrated


def _migrate_v60_to_v61(value: dict[str, Any]) -> dict[str, Any]:
    """Enable visual Top N report-filter clauses without changing existing filters."""
    migrated = deepcopy(value)
    migrated["format_version"] = 61
    return migrated


def _migrate_v61_to_v62(value: dict[str, Any]) -> dict[str, Any]:
    """Add a report-wide filter collection without changing page filters."""
    migrated = deepcopy(value)
    report = migrated.get("report", {})
    if isinstance(report, dict):
        report.setdefault("filters", [])
    migrated["format_version"] = 62
    return migrated


def _migrate_v62_to_v63(value: dict[str, Any]) -> dict[str, Any]:
    """Add per-table local calculated-column definitions."""
    migrated = deepcopy(value)
    model = migrated.setdefault("model", {})
    if isinstance(model, dict):
        for table in model.setdefault("tables", []):
            if isinstance(table, dict):
                table.setdefault("calculated_columns", [])
    migrated["format_version"] = 63
    return migrated


def _migrate_v63_to_v64(value: dict[str, Any]) -> dict[str, Any]:
    """Enable saved DAX calculated-table query definitions."""
    migrated = deepcopy(value)
    migrated["format_version"] = 64
    return migrated


def _migrate_v64_to_v65(value: dict[str, Any]) -> dict[str, Any]:
    """Add optional date-table column metadata to model tables."""
    migrated = deepcopy(value)
    model = migrated.setdefault("model", {})
    if isinstance(model, dict):
        for table in model.setdefault("tables", []):
            if isinstance(table, dict):
                table.setdefault("date_column", None)
    migrated["format_version"] = 65
    return migrated


def _migrate_v66_to_v67(value: dict[str, Any]) -> dict[str, Any]:
    """Advance v66 projects to the schema that supports hidden report pages."""
    migrated = deepcopy(value)
    report = migrated.get("report")
    if isinstance(report, dict):
        pages = report.get("pages")
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict):
                    page.setdefault("hidden", False)
    migrated["format_version"] = 67
    return migrated


def _migrate_v65_to_v66(value: dict[str, Any]) -> dict[str, Any]:
    """Enable saved CALENDAR and CALENDARAUTO query definitions."""
    migrated = deepcopy(value)
    migrated["format_version"] = 66
    return migrated


def _read_project(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectFileError(f"Could not read {path.name}: {exc}") from exc
    return validate_project(value)


def load_project(path: Path) -> tuple[dict[str, Any], bool]:
    """Load a project, falling back to its last known-good .bak after corruption."""
    path = Path(path)
    try:
        return _read_project(path), False
    except UnsupportedProjectVersion:
        # Do not silently replace a newer project with an older backup.
        raise
    except (ProjectFileError, FileNotFoundError) as primary_error:
        backup = Path(f"{path}.bak")
        if not backup.is_file():
            raise ProjectFileError(f"{primary_error} No recovery backup was found.") from primary_error
        try:
            return _read_project(backup), True
        except (ProjectFileError, FileNotFoundError) as backup_error:
            raise ProjectFileError(
                f"The project could not be opened ({primary_error}); its recovery copy also failed ({backup_error})."
            ) from backup_error


def _atomic_write(path: Path, contents: str) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def save_project(
    path: Path,
    document: dict[str, Any],
    *,
    recovered_from_backup: bool = False,
) -> dict[str, Any]:
    """Atomically save JSON and keep the previous good file as ``<name>.bak``."""
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = validate_project(document)
    value["modified_at"] = utc_now()
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"

    backup = Path(f"{path}.bak")
    if path.is_file() and not recovered_from_backup:
        fd, backup_temp_name = tempfile.mkstemp(
            prefix=f".{backup.name}.", suffix=".tmp", dir=backup.parent
        )
        os.close(fd)
        backup_temp = Path(backup_temp_name)
        try:
            shutil.copy2(path, backup_temp)
            with backup_temp.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(backup_temp, backup)
        finally:
            backup_temp.unlink(missing_ok=True)

    _atomic_write(path, payload)
    return value


def source_path_for_save(source_path: Path, project_path: Path) -> str:
    """Store linked data relative to the project when it is inside that folder."""
    source_path = Path(source_path).expanduser().resolve()
    project_dir = Path(project_path).expanduser().resolve().parent
    try:
        return source_path.relative_to(project_dir).as_posix()
    except ValueError:
        return str(source_path)


def resolve_source_path(stored_path: str, project_path: Path) -> Path:
    path = Path(stored_path).expanduser()
    if not path.is_absolute():
        path = Path(project_path).expanduser().resolve().parent / path
    return path.resolve()


def _migrate_v67_to_v68(value: dict[str, Any]) -> dict[str, Any]:
    """Migrate report page visuals from strings to explicit placement dictionaries."""
    from uuid import uuid4
    migrated = deepcopy(value)
    report = migrated.get("report")
    if isinstance(report, dict):
        pages = report.get("pages")
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict):
                    visuals = page.get("visuals")
                    if isinstance(visuals, list):
                        new_visuals = []
                        x_offset = 14
                        y_row2 = 108
                        for index, v in enumerate(visuals):
                            if isinstance(v, str):
                                new_visuals.append({
                                    "id": str(uuid4()),
                                    "type": "column" if "revenue" in v.lower() else "card",
                                    "title": v,
                                    "x": x_offset + (index * 344) % 688,
                                    "y": y_row2 if "revenue" in v.lower() else 14,
                                    "width": 330 if "revenue" in v.lower() else 120,
                                    "height": 248 if "revenue" in v.lower() else 80
                                })
                        page["visuals"] = new_visuals
    migrated["format_version"] = 68
    return migrated
