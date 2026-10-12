"""Validated user-defined scalar functions for the bounded local M subset."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import re
from typing import Any


MAX_QUERY_FUNCTIONS = 128
MAX_FUNCTION_EXPRESSION_LENGTH = 2_000
QUERY_FUNCTION_TYPES = (
    "text", "whole_number", "decimal_number", "boolean", "date", "datetime",
)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,119}\Z")
_RESERVED_NAMES = {
    "source", "let", "in", "true", "false", "null", "and", "or",
    "not", "if", "then", "else",
}
_M_NAMESPACE_ROOTS = {
    "binary", "combiner", "comparer", "date", "datetime", "datetimezone",
    "diagnostics", "duration", "error", "function", "guid", "hash", "list",
    "logical", "number", "record", "replacer", "splitter", "table", "text", "time",
    "type", "uri",
}
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


class QueryFunctionError(ValueError):
    """A Power Query scalar function definition or invocation is invalid."""


class QueryEvaluationContext(dict):
    """Parameter values plus the project functions used by formula evaluation."""

    def __init__(self, values: dict[str, Any], functions: Any = None) -> None:
        super().__init__(values)
        self.query_functions = validate_query_functions(functions or [])


def normalize_query_function(value: Any) -> dict[str, str]:
    required = {
        "name", "parameter", "parameter_type", "return_type", "expression",
    }
    optional = {"description"}
    if (
        not isinstance(value, dict)
        or set(value) - required - optional
        or not required.issubset(value)
    ):
        raise QueryFunctionError(
            "A function needs a name, one parameter, input and result types, and an expression."
        )
    name = value["name"]
    parameter = value["parameter"]
    parameter_type = value["parameter_type"]
    return_type = value["return_type"]
    expression = value["expression"]
    description = value.get("description", "")
    for role, identifier in (("function", name), ("parameter", parameter)):
        if (
            not isinstance(identifier, str)
            or not _NAME.fullmatch(identifier)
            or identifier.casefold() in _RESERVED_NAMES
        ):
            raise QueryFunctionError(
                f"The {role} name must be a valid non-reserved M identifier."
            )
        if identifier.casefold() in _M_NAMESPACE_ROOTS:
            raise QueryFunctionError(
                f"The {role} name cannot shadow an M library namespace."
            )
    if name.casefold() == parameter.casefold():
        raise QueryFunctionError("The function and its parameter must have different names.")
    for role, type_name in (("input", parameter_type), ("result", return_type)):
        if not isinstance(type_name, str) or type_name not in QUERY_FUNCTION_TYPES:
            raise QueryFunctionError(
                f"The function {role} type must be Text, Whole number, Decimal number, "
                "True/False, Date, or DateTime."
            )
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or len(expression) > MAX_FUNCTION_EXPRESSION_LENGTH
        or "\x00" in expression
    ):
        raise QueryFunctionError(
            f"A function expression must contain 1–{MAX_FUNCTION_EXPRESSION_LENGTH:,} characters."
        )
    if not isinstance(description, str) or len(description) > 1000 or "\x00" in description:
        raise QueryFunctionError("A function description must be at most 1,000 characters.")

    from analytics_studio.power_query_expression import (
        ExpressionError,
        compile_expression,
        referenced_columns,
    )

    try:
        body = compile_expression(expression, allowed_symbols={parameter})
    except ExpressionError as exc:
        raise QueryFunctionError(f"Function expression: {exc}") from exc
    if referenced_columns(body):
        raise QueryFunctionError(
            "A reusable scalar function body can reference its parameter, not table columns."
        )
    sample_value = {
        "text": "Sample",
        "whole_number": Decimal(7),
        "decimal_number": Decimal("7.5"),
        "boolean": True,
        "date": date(2026, 1, 15),
        "datetime": datetime(2026, 1, 15, 12, 30),
    }[parameter_type]
    try:
        from analytics_studio.power_query_expression import evaluate_expression

        sample_result = evaluate_expression(
            body, {}, {parameter: sample_value}
        )
        validate_function_result(return_type, sample_result)
    except (ExpressionError, QueryFunctionError) as exc:
        raise QueryFunctionError(
            f"The function expression does not produce its declared {return_type.replace('_', ' ')} result: {exc}"
        ) from exc
    result = {
        "name": name,
        "parameter": parameter,
        "parameter_type": parameter_type,
        "return_type": return_type,
        "expression": expression.strip(),
    }
    if description.strip():
        result["description"] = description.strip()
    return result


def validate_query_functions(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list) or len(values) > MAX_QUERY_FUNCTIONS:
        raise QueryFunctionError(
            f"A project may contain at most {MAX_QUERY_FUNCTIONS} Power Query functions."
        )
    result: list[dict[str, str]] = []
    names: set[str] = set()
    for value in values:
        function = normalize_query_function(value)
        key = function["name"].casefold()
        if key in names:
            raise QueryFunctionError(
                f"A Power Query function named {function['name']!r} already exists."
            )
        names.add(key)
        result.append(function)
    return result


def function_references(steps: Any, functions: Any = None) -> set[str]:
    """Return names of registered functions called by custom-column formulas."""
    from analytics_studio.power_query_expression import (
        ExpressionError,
        compile_expression,
        referenced_functions,
    )

    references: set[str] = set()
    known_names = {
        item["name"] for item in validate_query_functions(functions or [])
    }
    if not isinstance(steps, list):
        return references
    for step in steps:
        if not isinstance(step, dict) or step.get("op") != "add_custom_column":
            continue
        expression = step.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            continue
        try:
            tree = compile_expression(
                expression,
                allow_unknown_symbols=True,
                function_names=known_names,
            )
        except ExpressionError:
            continue
        references.update(referenced_functions(tree))
    return references


def compile_query_functions(values: Any) -> dict[str, tuple[dict[str, str], tuple[Any, ...]]]:
    """Validate and compile every function body once for a transformation replay."""
    from analytics_studio.power_query_expression import compile_expression

    compiled: dict[str, tuple[dict[str, str], tuple[Any, ...]]] = {}
    for function in validate_query_functions(values):
        body = compile_expression(
            function["expression"], allowed_symbols={function["parameter"]}
        )
        compiled[function["name"]] = (function, body)
    return compiled


def coerce_function_argument(type_name: str, value: Any) -> Any:
    if value is None:
        return None
    if type_name == "text":
        if isinstance(value, str):
            return value
    elif type_name in {"whole_number", "decimal_number"}:
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        except Exception:
            number = None
        if isinstance(number, Decimal) and number.is_finite():
            if type_name != "whole_number" or (
                number == number.to_integral_value()
                and _INT64_MIN <= number <= _INT64_MAX
            ):
                return number
    elif type_name == "boolean" and isinstance(value, bool):
        return value
    elif type_name == "boolean" and isinstance(value, str):
        if value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
    elif type_name == "date":
        if type(value) is date:
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip())
            except ValueError:
                pass
    elif type_name == "datetime":
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                pass
    raise QueryFunctionError(
        f"The function expects a {type_name.replace('_', ' ')} argument; "
        f"the expression returned {type(value).__name__}."
    )


def validate_function_result(type_name: str, value: Any) -> Any:
    if value is None:
        return None
    valid = False
    if type_name == "text":
        valid = isinstance(value, str)
    elif type_name in {"whole_number", "decimal_number"}:
        valid = isinstance(value, (Decimal, int)) and not isinstance(value, bool)
        if valid:
            number = value if isinstance(value, Decimal) else Decimal(value)
            valid = number.is_finite()
            if type_name == "whole_number":
                valid = (
                    valid
                    and number == number.to_integral_value()
                    and _INT64_MIN <= number <= _INT64_MAX
                )
            if valid:
                return number
    elif type_name == "boolean":
        valid = isinstance(value, bool)
    elif type_name == "date":
        valid = type(value) is date
    elif type_name == "datetime":
        valid = isinstance(value, datetime)
    if valid:
        return value
    raise QueryFunctionError(
        f"The function result must be {type_name.replace('_', ' ')}; "
        f"the expression returned {type(value).__name__}."
    )


def validate_typed_scalar(type_name: str, value: Any) -> Any:
    """Check that a formula result matches an output column's declared type."""
    if value is None:
        return None
    if type_name == "whole_number":
        try:
            number = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception as exc:
            raise QueryFunctionError("The result is not a whole number.") from exc
        if (
            not number.is_finite()
            or number != number.to_integral_value()
            or not _INT64_MIN <= number <= _INT64_MAX
        ):
            raise QueryFunctionError("The result is not a whole number.")
        return number
    return validate_function_result(type_name, value)


def query_function_to_m(function: dict[str, Any]) -> str:
    """Render one validated scalar function definition as a typed M binding."""
    item = normalize_query_function(function)
    m_types = {
        "text": "text",
        "whole_number": "Int64.Type",
        "decimal_number": "number",
        "boolean": "logical",
        "date": "date",
        "datetime": "datetime",
    }
    return (
        f"{item['name']} = ({item['parameter']} as nullable {m_types[item['parameter_type']]}) "
        f"as nullable {m_types[item['return_type']]} => {item['expression']}"
    )


__all__ = [
    "MAX_QUERY_FUNCTIONS",
    "QUERY_FUNCTION_TYPES",
    "QueryEvaluationContext",
    "QueryFunctionError",
    "compile_query_functions",
    "function_references",
    "normalize_query_function",
    "query_function_to_m",
    "validate_function_result",
    "validate_typed_scalar",
    "validate_query_functions",
]
