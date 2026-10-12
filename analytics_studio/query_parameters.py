"""Validated scalar parameters used by the local Power Query subset."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, DecimalException
import re
from typing import Any


MAX_QUERY_PARAMETERS = 128
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,119}\Z")
_RESERVED_NAMES = {
    "source", "let", "in", "true", "false", "null", "and", "or",
    "not", "if", "then", "else",
}
QUERY_PARAMETER_TYPES = (
    "text", "whole_number", "decimal_number", "boolean", "date", "datetime",
)


class QueryParameterError(ValueError):
    """A saved query parameter has an invalid name, type, or value."""


def normalize_query_parameter(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {
        "name", "type", "current_value", "description",
    } or not {"name", "type", "current_value"}.issubset(value):
        raise QueryParameterError(
            "A query parameter needs a name, type, current_value, and optional description."
        )
    name = value["name"]
    type_name = value["type"]
    current_value = value["current_value"]
    description = value.get("description", "")
    if (
        not isinstance(name, str)
        or not _NAME.fullmatch(name)
        or name.casefold() in _RESERVED_NAMES
    ):
        raise QueryParameterError(
            "Parameter names must be valid M identifiers and cannot use reserved words."
        )
    if not isinstance(type_name, str) or type_name not in QUERY_PARAMETER_TYPES:
        raise QueryParameterError(
            "Parameter type must be Text, Whole number, Decimal number, True/False, Date, or DateTime."
        )
    if not isinstance(current_value, str) or len(current_value) > 4000 or "\x00" in current_value:
        raise QueryParameterError("A parameter value must be text of at most 4,000 characters.")
    if not isinstance(description, str) or len(description) > 1000 or "\x00" in description:
        raise QueryParameterError("A parameter description must be text of at most 1,000 characters.")
    normalized_value = current_value.strip() if type_name != "text" else current_value
    if type_name == "whole_number":
        try:
            number = Decimal(normalized_value)
        except DecimalException as exc:
            raise QueryParameterError("A whole-number parameter needs an integer value.") from exc
        if not number.is_finite() or number != number.to_integral_value():
            raise QueryParameterError("A whole-number parameter needs an integer value.")
        normalized_value = str(int(number))
    elif type_name == "decimal_number":
        try:
            number = Decimal(normalized_value)
        except DecimalException as exc:
            raise QueryParameterError("A decimal-number parameter needs a finite number.") from exc
        if not number.is_finite():
            raise QueryParameterError("A decimal-number parameter needs a finite number.")
        normalized_value = str(number)
    elif type_name == "boolean":
        if normalized_value.casefold() not in {"true", "false"}:
            raise QueryParameterError("A True/False parameter must be true or false.")
        normalized_value = normalized_value.casefold()
    elif type_name == "date":
        try:
            normalized_value = date.fromisoformat(normalized_value).isoformat()
        except ValueError as exc:
            raise QueryParameterError("A Date parameter must use YYYY-MM-DD format.") from exc
    elif type_name == "datetime":
        try:
            parsed = datetime.fromisoformat(normalized_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise QueryParameterError("A DateTime parameter must use an ISO date and time.") from exc
        normalized_value = parsed.isoformat(timespec="auto")
    result = {"name": name, "type": type_name, "current_value": normalized_value}
    if description.strip():
        result["description"] = description.strip()
    return result


def validate_query_parameters(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list) or len(values) > MAX_QUERY_PARAMETERS:
        raise QueryParameterError(
            f"A project may contain at most {MAX_QUERY_PARAMETERS} query parameters."
        )
    result: list[dict[str, str]] = []
    names: set[str] = set()
    for value in values:
        parameter = normalize_query_parameter(value)
        key = parameter["name"].casefold()
        if key in names:
            raise QueryParameterError(
                f"A query parameter named {parameter['name']!r} already exists."
            )
        names.add(key)
        result.append(parameter)
    return result


def parameter_values(
    values: Any, query_functions: Any = None
) -> dict[str, Any]:
    """Return validated current values as scalar objects for expression evaluation."""
    parameters = validate_query_parameters(values if values is not None else [])
    result: dict[str, Any] = {}
    for item in parameters:
        value = item["current_value"]
        if item["type"] in {"whole_number", "decimal_number"}:
            result[item["name"]] = Decimal(value)
        elif item["type"] == "boolean":
            result[item["name"]] = value == "true"
        elif item["type"] == "date":
            result[item["name"]] = date.fromisoformat(value)
        elif item["type"] == "datetime":
            result[item["name"]] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            result[item["name"]] = value
    from analytics_studio.query_functions import QueryEvaluationContext

    return QueryEvaluationContext(result, query_functions)


def parameter_references(
    steps: Any, *, function_names: set[str] | None = None
) -> set[str]:
    references: set[str] = set()
    if not isinstance(steps, list):
        return references
    for step in steps:
        if not isinstance(step, dict):
            continue
        if isinstance(step.get("parameter"), str):
            references.add(step["parameter"])
        expression = step.get("expression")
        if isinstance(expression, str) and expression.strip():
            from analytics_studio.power_query_expression import (
                compile_expression,
                referenced_symbols,
            )

            tree = compile_expression(
                expression,
                allow_unknown_symbols=True,
                function_names=function_names,
                allow_unknown_functions=True,
            )
            references.update(referenced_symbols(tree))
        for clause in step.get("clauses", []):
            if isinstance(clause, dict) and isinstance(clause.get("parameter"), str):
                references.add(clause["parameter"])
    return references
