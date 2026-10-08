"""A deliberately small, safe DAX evaluator for local model calculations.

Supported expressions use scalar arithmetic, aggregate functions, and the
numeric functions ABS and ROUND. Measures also support conditionals and the
SUMX/AVERAGEX iterators. Calculated columns use a bounded row-scoped subset of
numeric and boolean expressions. Measures also support marked-date-table
calendar- and fiscal-year TOTALYTD, calendar-quarter TOTALQTD, calendar-month TOTALMTD, and
DATEADD, SAMEPERIODLASTYEAR, DATESYTD, DATESQTD, DATESMTD, DATESBETWEEN,
and DATESINPERIOD, PREVIOUSYEAR, PREVIOUSQUARTER, and PREVIOUSMONTH filters in the supported
CALCULATE form. Measures also support a bounded CALCULATE Boolean-filter subset
with typed column comparisons, same-column replacement, multiple ANDed filters,
and KEEPFILTERS intersection, plus one table-valued FILTER argument with a
same-table row predicate. CALCULATE also supports the no-argument, table, and
qualified-column forms of REMOVEFILTERS, ALL, ALLNOBLANKROW, ALLEXCEPT, and
ALLSELECTED as
sole filter modifiers. ALLEXCEPT preserves named same-table column filters
and clears the other direct filters from that table. ALL table values preserve table rows or distinct column tuples for
COUNTROWS, SUMX, and AVERAGEX, including one virtual blank parent row for
unmatched relationship keys. ALLNOBLANKROW table values omit that virtual row
while retaining physical blank rows and values.
ALLSELECTED table values retain the currently visible rows or distinct column
tuples. Its modifier form preserves the saved selection context; visual query
row/column filters are not modeled by this local report evaluator.
USERELATIONSHIP accepts saved relationship endpoint columns as one or more
sole CALCULATE filter modifiers. Selected links are temporary; nested
calculations restore the prior relationship context.
CROSSFILTER temporarily changes the direction of active saved links in
CALCULATE, including disabling the link for the calculation.
The module parses into a tiny AST and never evaluates user text as Python.
"""

from __future__ import annotations

from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from datetime import date, datetime, time, timedelta
import re
from typing import Any, Iterable

from analytics_studio.relationships import (
    RelationshipError,
    propagate_relationship_filters,
    relationship_filter_directions,
    unknown_member_table_ids,
)


class MeasureError(ValueError):
    """A measure definition is invalid or cannot be evaluated for this table."""


MAX_MEASURES = 100
MAX_CALCULATED_COLUMNS = 100
MAX_EXPRESSION_LENGTH = 2_000
MAX_TOKENS = 512

_FUNCTIONS = {
    "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "DISTINCTCOUNT",
    "COUNTROWS", "DIVIDE", "ABS", "ROUND", "IF", "AND", "OR", "NOT",
    "SUMX", "AVERAGEX", "TOTALYTD", "TOTALQTD", "TOTALMTD",
    "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN", "DATESINPERIOD",
    "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH",
    "DATEADD", "SAMEPERIODLASTYEAR", "CALCULATE", "KEEPFILTERS", "FILTER",
    "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED",
    "USERELATIONSHIP", "CROSSFILTER",
}
_TIME_FILTER_FUNCTIONS = {
    "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
    "PREVIOUSMONTH", "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN",
    "DATESINPERIOD",
}
_CROSSFILTER_DIRECTIONS = {
    "NONE", "BOTH", "ONEWAY", "ONEWAY_LEFTFILTERSRIGHT",
    "ONEWAY_RIGHTFILTERSLEFT",
}
_TOKEN_PATTERN = re.compile(
    r"(?P<table_ref>'(?:[^']|'')+'\s*\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*\s*\[[^\]]+\])"
    r"|(?P<table_name>'(?:[^']|'')+')"
    r"|(?P<ref>\[[^\]\r\n]+\])"
    r"|(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r'|(?P<string>"(?:[^"]|"")*")'
    r"|(?P<identifier>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<operator><>|<=|>=|&&|\|\||[()+\-*/,=<>])"
)
_FORMULA_ASSIGNMENT = re.compile(
    r"^\s*(?:\[(?P<bracketed>[^\]\r\n]+)\]|"
    r"(?P<plain>[^()\[\],<>!+=*/\r\n]+?))\s*=\s*(?![=<>])"
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str


def tokenize(expression: str) -> list[Token]:
    if not isinstance(expression, str) or not expression.strip():
        raise MeasureError("Enter a DAX expression.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise MeasureError(f"A DAX expression can contain at most {MAX_EXPRESSION_LENGTH:,} characters.")
    tokens: list[Token] = []
    position = 0
    while position < len(expression):
        if expression[position].isspace():
            position += 1
            continue
        match = _TOKEN_PATTERN.match(expression, position)
        if match is None:
            raise MeasureError(f"Unsupported character at position {position + 1}.")
        kind = match.lastgroup or ""
        value = match.group()
        if kind == "table_name":
            tokens.append(Token("table", value[1:-1].replace("''", "'")))
        elif kind in {"ref", "table_ref"}:
            column = value.rsplit("[", 1)[1][:-1].strip()
            if not column:
                raise MeasureError("A column reference cannot be empty.")
            table = value.split("[", 1)[0].strip().strip("'").replace("''", "'") if kind == "table_ref" else ""
            tokens.append(Token("reference", f"{table}\0{column}"))
        elif kind == "number":
            tokens.append(Token(kind, value))
        elif kind == "string":
            tokens.append(Token(kind, value[1:-1].replace('""', '"')))
        elif kind == "identifier":
            tokens.append(Token(kind, value.upper()))
        else:
            tokens.append(Token(value, value))
        if len(tokens) > MAX_TOKENS:
            raise MeasureError(f"A DAX expression can contain at most {MAX_TOKENS} tokens.")
        position = match.end()
    return tokens


def _parse_year_end_date(value: Any) -> tuple[int, int]:
    """Validate the local evaluator's invariant numeric M/D year-end subset."""
    if not isinstance(value, str):
        raise MeasureError('year_end_date must use month/day, such as "6/30".')
    match = re.fullmatch(r"\s*([0-9]{1,2})/([0-9]{1,2})\s*", value)
    if match is None:
        raise MeasureError('year_end_date must use month/day, such as "6/30".')
    month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12 or not 1 <= day <= monthrange(2000, month)[1]:
        raise MeasureError('year_end_date must be a valid month/day, such as "6/30".')
    return month, day


def _parse_iso_date_literal(value: Any, function: str) -> date:
    """Parse the local ISO date literal format for a time-intelligence function."""
    if not isinstance(value, str):
        raise MeasureError(
            f'{function} date literals must use ISO dates, such as "2024-01-31".'
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MeasureError(
            f'{function} date literals must use ISO dates, such as "2024-01-31".'
        ) from exc
    if parsed.isoformat() != value:
        raise MeasureError(
            f'{function} date literals must use ISO dates, such as "2024-01-31".'
        )
    return parsed


def _year_to_date_start(end_date: date, year_end: tuple[int, int]) -> date:
    """Return the first day of the calendar or fiscal year containing end_date."""
    year_end_month, year_end_day = year_end
    current_year_end = date(
        end_date.year,
        year_end_month,
        min(year_end_day, monthrange(end_date.year, year_end_month)[1]),
    )
    if end_date > current_year_end:
        return current_year_end + timedelta(days=1)
    if end_date.year > date.min.year:
        prior_year_end = date(
            end_date.year - 1,
            year_end_month,
            min(year_end_day, monthrange(end_date.year - 1, year_end_month)[1]),
        )
        return prior_year_end + timedelta(days=1)
    return date.min


def _previousyear_dates(
    selected_dates: Iterable[date],
    available_dates: Iterable[date],
    year_end: tuple[int, int] = (12, 31),
) -> set[date]:
    """Return the prior full calendar or fiscal year for the first selected date."""
    selected = tuple(selected_dates)
    if not selected:
        return set()

    current_year_start = _year_to_date_start(min(selected), year_end)
    if current_year_start == date.min:
        return set()
    previous_year_end = current_year_start - timedelta(days=1)
    previous_year_start = _year_to_date_start(previous_year_end, year_end)
    return {
        value for value in available_dates
        if previous_year_start <= value <= previous_year_end
    }


def _previousquarter_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date]
) -> set[date]:
    """Return the full calendar quarter before the quarter of the first date."""
    selected = tuple(selected_dates)
    if not selected:
        return set()

    first_date = min(selected)
    current_quarter_start = date(
        first_date.year, ((first_date.month - 1) // 3) * 3 + 1, 1
    )
    if current_quarter_start == date.min:
        return set()
    previous_quarter_end = current_quarter_start - timedelta(days=1)
    previous_quarter_start = date(
        previous_quarter_end.year,
        ((previous_quarter_end.month - 1) // 3) * 3 + 1,
        1,
    )
    return {
        value for value in available_dates
        if previous_quarter_start <= value <= previous_quarter_end
    }


def _previousmonth_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date]
) -> set[date]:
    """Return the full calendar month before the month of the first date."""
    selected = tuple(selected_dates)
    if not selected:
        return set()

    first_date = min(selected)
    current_month_start = date(first_date.year, first_date.month, 1)
    if current_month_start == date.min:
        return set()
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = date(
        previous_month_end.year, previous_month_end.month, 1
    )
    return {
        value for value in available_dates
        if previous_month_start <= value <= previous_month_end
    }


def _calculate_filter_argument(node: tuple[Any, ...]) -> tuple[tuple[Any, ...], bool]:
    """Unwrap the one supported CALCULATE filter modifier."""
    if node[0] == "call" and node[1] == "KEEPFILTERS":
        if len(node[2]) != 1:
            raise MeasureError("KEEPFILTERS needs one Boolean filter expression.")
        return node[2][0], True
    return node, False


def _is_filter_scalar(node: Any) -> bool:
    """Return whether a Boolean filter side is a bounded constant expression."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] in {"number", "string", "boolean", "blank"}:
        return True
    if node[0] == "unary":
        return node[2][0] == "number"
    if node[0] == "binary":
        return _is_filter_scalar(node[2]) and _is_filter_scalar(node[3]) and all(
            child[0] in {"number", "unary", "binary"}
            for child in (node[2], node[3])
        )
    return False


def _calculate_boolean_filter_column(node: tuple[Any, ...]) -> tuple[str, str]:
    """Validate a simple Boolean CALCULATE filter and return its sole column."""
    if not isinstance(node, tuple) or not node:
        raise MeasureError("CALCULATE filters must be supported Boolean comparisons.")
    kind = node[0]
    if kind == "comparison":
        left, right = node[2], node[3]
        left_is_reference = left[0] == "reference"
        right_is_reference = right[0] == "reference"
        if left_is_reference == right_is_reference:
            raise MeasureError(
                "Each CALCULATE comparison must compare one column with a scalar literal."
            )
        reference, scalar = (left, right) if left_is_reference else (right, left)
        if not _is_filter_scalar(scalar):
            raise MeasureError(
                "CALCULATE comparisons support one column and a scalar literal only."
            )
        return reference[1].casefold(), reference[2].casefold()
    if kind == "logical":
        left = _calculate_boolean_filter_column(node[2])
        right = _calculate_boolean_filter_column(node[3])
        if left != right:
            raise MeasureError(
                "One CALCULATE Boolean filter can reference only one column."
            )
        return left
    if kind == "call" and node[1] in {"AND", "OR", "NOT"}:
        expected = 1 if node[1] == "NOT" else 2
        if len(node[2]) != expected:
            raise MeasureError(f"{node[1]} needs {expected} logical expression(s).")
        columns = {
            _calculate_boolean_filter_column(argument)
            for argument in node[2]
        }
        if len(columns) != 1:
            raise MeasureError(
                "One CALCULATE Boolean filter can reference only one column."
            )
        return next(iter(columns))
    raise MeasureError(
        "CALCULATE filters must be column comparisons joined with AND, OR, or NOT."
    )


def _calculate_table_filter_predicate(
    node: tuple[Any, ...], table_name: str
) -> None:
    """Validate FILTER's bounded qualified-column predicate for one table."""
    if node[0] == "comparison":
        left, right = node[2], node[3]
        left_is_reference = left[0] == "reference"
        right_is_reference = right[0] == "reference"
        if left_is_reference == right_is_reference:
            raise MeasureError(
                "FILTER predicates must use a column comparison with one scalar literal."
            )
        reference, scalar = (left, right) if left_is_reference else (right, left)
        if not _is_filter_scalar(scalar):
            raise MeasureError(
                "FILTER predicates must use column comparisons with scalar literals."
            )
        if not reference[1]:
            raise MeasureError(
                "FILTER predicates must use qualified columns from the FILTER table."
            )
        if reference[1].casefold() != table_name.casefold():
            raise MeasureError(
                "FILTER predicates can reference columns from the same loaded table only."
            )
        return
    if node[0] == "logical":
        _calculate_table_filter_predicate(node[2], table_name)
        _calculate_table_filter_predicate(node[3], table_name)
        return
    if node[0] == "call" and node[1] in {"AND", "OR", "NOT"}:
        expected = 1 if node[1] == "NOT" else 2
        if len(node[2]) != expected:
            raise MeasureError(f"{node[1]} needs {expected} logical expression(s).")
        for argument in node[2]:
            _calculate_table_filter_predicate(argument, table_name)
        return
    raise MeasureError(
        "FILTER predicates must be column comparisons joined with AND, OR, or NOT."
    )


def _validate_table_filter_call(node: tuple[Any, ...]) -> None:
    if len(node[2]) != 2 or node[2][0][0] != "table":
        raise MeasureError(
            "FILTER currently needs a base table name and one row predicate."
        )
    _calculate_table_filter_predicate(node[2][1], str(node[2][0][1]))


def _validate_filter_clear_call(node: tuple[Any, ...], function: str) -> None:
    """Validate the local table-or-columns forms of filter-clearing functions."""
    arguments = node[2]
    if not arguments:
        return
    if len(arguments) == 1 and arguments[0][0] == "table":
        return
    if any(argument[0] != "reference" for argument in arguments):
        raise MeasureError(
            f"{function} needs no arguments, one table name, or qualified columns from one table."
        )
    table_names = {argument[1].casefold() for argument in arguments if argument[1]}
    if any(not argument[1] for argument in arguments) or len(table_names) != 1:
        raise MeasureError(
            f"{function} column arguments must be qualified columns from one table."
        )


def _validate_allexcept_call(node: tuple[Any, ...]) -> None:
    """Validate the base-table and same-table base-column ALLEXCEPT form."""
    arguments = node[2]
    if len(arguments) < 2 or arguments[0][0] != "table":
        raise MeasureError(
            "ALLEXCEPT needs one base table followed by one or more qualified columns from that table."
        )
    table_name = str(arguments[0][1]).casefold()
    if any(
        argument[0] != "reference"
        or not argument[1]
        or argument[1].casefold() != table_name
        for argument in arguments[1:]
    ):
        raise MeasureError(
            "ALLEXCEPT columns must be qualified base columns from its first table."
        )


def _validate_userelationship_call(node: tuple[Any, ...]) -> None:
    """Validate two fully qualified saved relationship endpoint columns."""
    arguments = node[2]
    if (
        len(arguments) != 2
        or any(argument[0] != "reference" or not argument[1] for argument in arguments)
    ):
        raise MeasureError(
            "USERELATIONSHIP needs two fully qualified column references from an existing relationship."
        )


def _validate_crossfilter_call(node: tuple[Any, ...]) -> None:
    """Validate endpoint columns and a documented CROSSFILTER direction."""
    arguments = node[2]
    if (
        len(arguments) != 3
        or any(argument[0] != "reference" or not argument[1] for argument in arguments[:2])
        or arguments[2][0] != "table"
        or str(arguments[2][1]).upper() not in _CROSSFILTER_DIRECTIONS
    ):
        raise MeasureError(
            "CROSSFILTER needs two fully qualified relationship columns and one supported direction."
        )


def _is_all_table_value_argument(node: Any) -> bool:
    """Return whether a node is a supported filter-function table value."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "table":
        return True
    if node[0] != "call" or node[1] not in {"ALL", "ALLNOBLANKROW", "ALLSELECTED"} or not node[2]:
        return False
    arguments = node[2]
    if len(arguments) == 1 and arguments[0][0] == "table":
        return True
    if any(argument[0] != "reference" or not argument[1] for argument in arguments):
        return False
    return len({argument[1].casefold() for argument in arguments}) == 1


def _has_supported_all_usage(
    node: Any,
    parent_function: str = "",
    argument_index: int = -1,
    parent_argument_count: int = 0,
) -> bool:
    """Validate that each ALL call occupies a supported scalar/table position."""
    if not isinstance(node, tuple) or not node:
        return True
    if node[0] == "table_call":
        return False
    if node[0] == "call":
        function, arguments = node[1], node[2]
        if function in {
            "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
            "PREVIOUSMONTH", "DATESYTD", "DATESQTD", "DATESMTD",
            "DATESBETWEEN", "DATESINPERIOD", "FILTER",
        }:
            return False
        if function == "ALLEXCEPT":
            try:
                _validate_allexcept_call(node)
            except MeasureError:
                return False
            return (
                parent_function == "CALCULATE"
                and argument_index == 1
                and parent_argument_count == 2
            )
        if function in {"ALL", "ALLNOBLANKROW", "ALLSELECTED"}:
            try:
                _validate_filter_clear_call(node, function)
                if function == "ALLNOBLANKROW" and not arguments:
                    return False
            except MeasureError:
                return False
            valid_position = (
                parent_function == "CALCULATE"
                and argument_index == 1
                and parent_argument_count == 2
            ) or (
                parent_function in {"SUMX", "AVERAGEX", "COUNTROWS"}
                and argument_index == 0
                and _is_all_table_value_argument(node)
            )
            return valid_position
        return all(
            _has_supported_all_usage(
                argument, function, index, len(arguments)
            )
            for index, argument in enumerate(arguments)
        )
    return all(
        _has_supported_all_usage(child)
        for child in node[1:]
        if isinstance(child, tuple)
    )


def _contains_function_call(node: Any, function: str) -> bool:
    if not isinstance(node, tuple) or not node:
        return False
    return (
        (node[0] == "call" and node[1] == function)
        or any(
            isinstance(child, tuple) and _contains_function_call(child, function)
            for child in node
        )
    )


def _iter_reference_nodes(node: Any) -> Iterable[tuple[Any, ...]]:
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "reference":
        yield node
        return
    for child in node[1:]:
        if isinstance(child, tuple):
            yield from _iter_reference_nodes(child)


def _validate_literal_positions(node: tuple[Any, ...]) -> None:
    """Keep literals in time-intelligence syntax or validated CALCULATE filters."""
    kind = node[0]
    if kind == "string":
        raise MeasureError(
            "String literals are supported only as time-intelligence arguments."
        )
    if kind == "blank":
        raise MeasureError("BLANK() is supported only as a DATESBETWEEN bound.")
    if kind == "omitted":
        raise MeasureError("Only TOTALYTD's optional filter argument can be omitted.")
    if kind == "call":
        function, arguments = node[1], node[2]
        if function == "CALCULATE":
            if not arguments:
                raise MeasureError("CALCULATE needs an expression.")
            _validate_literal_positions(arguments[0])
            contains_userelationship = any(
                _contains_function_call(argument, "USERELATIONSHIP")
                for argument in arguments[1:]
            )
            if contains_userelationship:
                if not arguments[1:] or any(
                    argument[0] != "call" or argument[1] != "USERELATIONSHIP"
                    for argument in arguments[1:]
                ):
                    raise MeasureError(
                        "USERELATIONSHIP must be the only kind of CALCULATE filter argument in this local subset."
                    )
                for modifier in arguments[1:]:
                    _validate_userelationship_call(modifier)
                return
            contains_crossfilter = any(
                _contains_function_call(argument, "CROSSFILTER")
                for argument in arguments[1:]
            )
            if contains_crossfilter:
                if not arguments[1:] or any(
                    argument[0] != "call" or argument[1] != "CROSSFILTER"
                    for argument in arguments[1:]
                ):
                    raise MeasureError(
                        "CROSSFILTER must be the only kind of CALCULATE filter argument in this local subset."
                    )
                for modifier in arguments[1:]:
                    _validate_crossfilter_call(modifier)
                return
            valid_filter_clear = (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1] in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED"}
            )
            contained_filter_clear = {
                function
                for function in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED"}
                if any(
                    _contains_function_call(argument, function)
                    for argument in arguments[1:]
                )
            }
            if contained_filter_clear:
                if not valid_filter_clear:
                    function = sorted(contained_filter_clear)[0]
                    raise MeasureError(
                        f"{function} must be the only CALCULATE filter argument in this local subset."
                    )
                if arguments[1][1] == "ALLEXCEPT":
                    _validate_allexcept_call(arguments[1])
                else:
                    _validate_filter_clear_call(arguments[1], arguments[1][1])
                return
            if (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1] == "FILTER"
            ):
                _validate_table_filter_call(arguments[1])
                return
            if any(_contains_function_call(argument, "FILTER") for argument in arguments[1:]):
                raise MeasureError(
                    "A table-valued FILTER must be the only CALCULATE filter argument."
                )
            if (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1] in _TIME_FILTER_FUNCTIONS
            ):
                _validate_literal_positions(arguments[1])
                return
            for filter_argument in arguments[1:]:
                predicate, _keep = _calculate_filter_argument(filter_argument)
                _calculate_boolean_filter_column(predicate)
            return
        if function in {"SUMX", "AVERAGEX"}:
            _validate_literal_positions(arguments[1])
            return
        if function == "COUNTROWS":
            return
        if function == "FILTER":
            raise MeasureError(
                "FILTER is supported only as the sole table-valued CALCULATE filter argument."
            )
        if function == "KEEPFILTERS":
            raise MeasureError("KEEPFILTERS is supported only as a CALCULATE filter argument.")
        if function == "USERELATIONSHIP":
            raise MeasureError(
                "USERELATIONSHIP is supported only as a CALCULATE filter modifier."
            )
        if function == "CROSSFILTER":
            raise MeasureError(
                "CROSSFILTER is supported only as a CALCULATE filter modifier."
            )
        if function == "REMOVEFILTERS":
            raise MeasureError(
                "REMOVEFILTERS is supported only as a CALCULATE filter modifier."
            )
        if function in {"ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED"}:
            raise MeasureError(
                f"{function} is supported only as a CALCULATE filter modifier or "
                "a COUNTROWS/SUMX/AVERAGEX table expression in this local subset."
            )
        for index, argument in enumerate(arguments):
            if function == "TOTALYTD" and index == 3 and argument[0] == "string":
                _parse_year_end_date(argument[1])
            elif function == "DATESYTD" and index == 1 and argument[0] == "string":
                _parse_year_end_date(argument[1])
            elif function == "DATESBETWEEN" and index in {1, 2}:
                if argument[0] == "string":
                    _parse_iso_date_literal(argument[1], "DATESBETWEEN")
                elif argument[0] == "blank":
                    continue
            elif function == "DATESINPERIOD" and index == 1 and argument[0] == "string":
                _parse_iso_date_literal(argument[1], "DATESINPERIOD")
            elif function == "PREVIOUSYEAR" and index == 1 and argument[0] == "string":
                _parse_year_end_date(argument[1])
            elif function == "TOTALYTD" and index == 2 and argument[0] == "omitted":
                continue
            else:
                _validate_literal_positions(argument)
        return
    for child in node[1:]:
        if isinstance(child, tuple) and child:
            _validate_literal_positions(child)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def parse(self) -> tuple[Any, ...]:
        if not self.tokens:
            raise MeasureError("Enter a DAX expression.")
        node = self._expression()
        if self.index != len(self.tokens):
            raise MeasureError(f"Unexpected token {self.tokens[self.index].value!r}.")
        _validate_literal_positions(node)
        return node

    def _expression(self) -> tuple[Any, ...]:
        return self._logical_or()

    def _logical_or(self) -> tuple[Any, ...]:
        node = self._logical_and()
        while self._peek() == "||":
            self._take()
            node = ("logical", "||", node, self._logical_and())
        return node

    def _logical_and(self) -> tuple[Any, ...]:
        node = self._comparison()
        while self._peek() == "&&":
            self._take()
            node = ("logical", "&&", node, self._comparison())
        return node

    def _comparison(self) -> tuple[Any, ...]:
        node = self._arithmetic()
        if self._peek() in {"=", "<>", "<", "<=", ">", ">="}:
            operator = self._take().kind
            node = ("comparison", operator, node, self._arithmetic())
            if self._peek() in {"=", "<>", "<", "<=", ">", ">="}:
                raise MeasureError("Comparison operators cannot be chained; combine conditions with AND or OR.")
        return node

    def _arithmetic(self) -> tuple[Any, ...]:
        node = self._term()
        while self._peek() in {"+", "-"}:
            operator = self._take().kind
            node = ("binary", operator, node, self._term())
        return node

    def _term(self) -> tuple[Any, ...]:
        node = self._unary()
        while self._peek() in {"*", "/"}:
            operator = self._take().kind
            node = ("binary", operator, node, self._unary())
        return node

    def _unary(self) -> tuple[Any, ...]:
        if self._peek() in {"+", "-"}:
            operator = self._take().kind
            return ("unary", operator, self._unary())
        return self._primary()

    def _primary(self) -> tuple[Any, ...]:
        token = self._take()
        if token.kind == "number":
            try:
                value = Decimal(token.value)
            except DecimalException as exc:
                raise MeasureError(f"Invalid numeric literal {token.value!r}.") from exc
            if not value.is_finite():
                raise MeasureError("Numeric literals must be finite.")
            return ("number", value)
        if token.kind == "string":
            return ("string", token.value)
        if token.kind == "(":
            node = self._expression()
            self._expect(")")
            return node
        if token.kind == "reference":
            table, column = token.value.split("\0", 1)
            return ("reference", table, column)
        if token.kind == "table":
            return ("table", token.value)
        if token.kind == "identifier":
            function = token.value
            if function in {"TRUE", "FALSE"}:
                if self._peek() == "(":
                    self._take()
                    self._expect(")")
                return ("boolean", function == "TRUE")
            if function == "BLANK":
                self._expect("(")
                self._expect(")")
                return ("blank",)
            if function == "DISTINCT":
                self._expect("(")
                argument = self._expression()
                self._expect(")")
                if argument[0] != "reference":
                    raise MeasureError("DISTINCT needs one source column reference.")
                return ("table_call", function, argument)
            if function not in _FUNCTIONS:
                if self._peek() in {",", ")"}:
                    return ("table", function)
                raise MeasureError(f"Function {function} is not supported by the local DAX engine.")
            self._expect("(")
            arguments: list[tuple[Any, ...]] = []
            if self._peek() != ")":
                while True:
                    if self._peek() == ",":
                        arguments.append(("omitted",))
                    else:
                        arguments.append(self._expression())
                    if self._peek() != ",":
                        break
                    self._take()
                    if self._peek() == ")":
                        arguments.append(("omitted",))
                        break
            self._expect(")")
            if function in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "DISTINCTCOUNT"}:
                if len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(f"{function} needs one column reference, such as {function}([Amount]).")
            elif function == "COUNTROWS" and (
                len(arguments) > 1
                or (arguments and not _is_all_table_value_argument(arguments[0]))
            ):
                raise MeasureError(
                    "COUNTROWS needs no argument or one loaded table/ALL table expression."
                )
            elif function == "DIVIDE" and len(arguments) not in {2, 3}:
                raise MeasureError("DIVIDE needs a numerator, denominator, and optional alternate result.")
            elif function == "ABS" and len(arguments) != 1:
                raise MeasureError("ABS needs one numeric expression.")
            elif function == "ROUND" and len(arguments) != 2:
                raise MeasureError("ROUND needs a numeric expression and a number of digits.")
            elif function == "IF" and len(arguments) != 3:
                raise MeasureError("IF needs a condition, a value for true, and a value for false.")
            elif function in {"AND", "OR"} and len(arguments) != 2:
                raise MeasureError(f"{function} needs two logical expressions.")
            elif function == "NOT" and len(arguments) != 1:
                raise MeasureError("NOT needs one logical expression.")
            elif function == "KEEPFILTERS" and len(arguments) != 1:
                raise MeasureError("KEEPFILTERS needs one filter expression.")
            elif function in {"SUMX", "AVERAGEX"} and (
                len(arguments) != 2
                or not _is_all_table_value_argument(arguments[0])
            ):
                raise MeasureError(
                    f"{function} needs a loaded table or ALL table expression and one scalar expression."
                )
            elif function == "TOTALYTD":
                date_argument_is_valid = (
                    len(arguments) >= 2 and arguments[1][0] == "reference"
                )
                default_year = len(arguments) == 2 and date_argument_is_valid
                fiscal_year = (
                    len(arguments) == 4
                    and date_argument_is_valid
                    and arguments[2][0] == "omitted"
                    and arguments[3][0] == "string"
                )
                if not (default_year or fiscal_year):
                    raise MeasureError(
                        'TOTALYTD needs an expression and marked date-column reference; '
                        'fiscal year end uses TOTALYTD(expression, date, , "M/D"). '
                        "Filter expressions are not supported."
                    )
                if fiscal_year:
                    _parse_year_end_date(arguments[3][1])
            elif function in {"TOTALQTD", "TOTALMTD"}:
                if len(arguments) != 2 or arguments[1][0] != "reference":
                    raise MeasureError(
                        f"{function} needs an expression and marked date-column reference. "
                        "Filter expressions are not supported."
                    )
            elif function == "DATESYTD":
                valid_arguments = (
                    len(arguments) == 1 and arguments[0][0] == "reference"
                ) or (
                    len(arguments) == 2
                    and arguments[0][0] == "reference"
                    and arguments[1][0] == "string"
                )
                if not valid_arguments:
                    raise MeasureError(
                        'DATESYTD needs a marked date-column reference and optional '
                        'M/D year-end string, such as DATESYTD(\'Calendar\'[Date], "6/30").'
                )
                if len(arguments) == 2:
                    _parse_year_end_date(arguments[1][1])
            elif function == "DATESQTD":
                if len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(
                        "DATESQTD needs one marked date-column reference."
                    )
            elif function == "DATESMTD":
                if len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(
                        "DATESMTD needs one marked date-column reference."
                    )
            elif function == "DATESBETWEEN":
                valid_arguments = (
                    len(arguments) == 3
                    and arguments[0][0] == "reference"
                    and arguments[1][0] in {"string", "blank"}
                    and arguments[2][0] in {"string", "blank"}
                )
                if not valid_arguments:
                    raise MeasureError(
                        'DATESBETWEEN needs a marked date-column reference and ISO '
                        'date or BLANK() start/end bounds.'
                    )
            elif function == "DATESINPERIOD":
                interval_node = arguments[2] if len(arguments) == 4 else ()
                numeric_interval = (
                    interval_node[0] == "number"
                    or (
                        interval_node[0] == "unary"
                        and interval_node[1] in {"+", "-"}
                        and interval_node[2][0] == "number"
                    )
                ) if interval_node else False
                valid_interval = (
                    len(arguments) == 4
                    and arguments[0][0] == "reference"
                    and arguments[1][0] == "string"
                    and numeric_interval
                    and arguments[3][0] == "table"
                    and str(arguments[3][1]).upper()
                    in {"DAY", "MONTH", "QUARTER", "YEAR"}
                )
                if not valid_interval:
                    raise MeasureError(
                        "DATESINPERIOD needs a marked date-column reference, an ISO "
                        "date string, an integer interval count, and DAY, MONTH, "
                        "QUARTER, or YEAR."
                    )
            elif function == "DATEADD":
                valid_interval = (
                    len(arguments) == 3
                    and arguments[0][0] == "reference"
                    and arguments[2][0] == "table"
                    and str(arguments[2][1]).upper() in {"YEAR", "QUARTER", "MONTH", "DAY"}
                )
                if not valid_interval or arguments[1][0] in {"table", "string", "omitted"}:
                    raise MeasureError(
                        "DATEADD needs a date-column reference, numeric interval count, "
                        "and YEAR, QUARTER, MONTH, or DAY interval."
                    )
            elif function == "SAMEPERIODLASTYEAR":
                if len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(
                        "SAMEPERIODLASTYEAR needs one marked date-column reference."
                    )
            elif function == "PREVIOUSYEAR":
                valid_arguments = (
                    len(arguments) == 1 and arguments[0][0] == "reference"
                ) or (
                    len(arguments) == 2
                    and arguments[0][0] == "reference"
                    and arguments[1][0] == "string"
                )
                if not valid_arguments:
                    raise MeasureError(
                        "PREVIOUSYEAR needs a marked date-column reference and an "
                        "optional M/D year-end string."
                    )
                if len(arguments) == 2:
                    _parse_year_end_date(arguments[1][1])
            elif function in {"PREVIOUSQUARTER", "PREVIOUSMONTH"}:
                if len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(
                        f"{function} needs one marked date-column reference."
                    )
            elif function == "FILTER":
                _validate_table_filter_call(("call", function, tuple(arguments)))
            elif function in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLSELECTED"}:
                _validate_filter_clear_call(
                    ("call", function, tuple(arguments)), function
                )
                if function == "ALLNOBLANKROW" and not arguments:
                    raise MeasureError("ALLNOBLANKROW needs a table or column argument.")
            elif function == "ALLEXCEPT":
                _validate_allexcept_call(("call", function, tuple(arguments)))
            elif function == "USERELATIONSHIP":
                _validate_userelationship_call(("call", function, tuple(arguments)))
            elif function == "CROSSFILTER":
                _validate_crossfilter_call(("call", function, tuple(arguments)))
            elif function == "CALCULATE":
                if not arguments:
                    raise MeasureError("CALCULATE needs an expression.")
                contains_userelationship = any(
                    _contains_function_call(argument, "USERELATIONSHIP")
                    for argument in arguments[1:]
                )
                if contains_userelationship:
                    if not arguments[1:] or any(
                        argument[0] != "call" or argument[1] != "USERELATIONSHIP"
                        for argument in arguments[1:]
                    ):
                        raise MeasureError(
                            "USERELATIONSHIP must be the only kind of CALCULATE filter argument in this local subset."
                        )
                    for modifier in arguments[1:]:
                        _validate_userelationship_call(modifier)
                    return ("call", function, tuple(arguments))
                contains_crossfilter = any(
                    _contains_function_call(argument, "CROSSFILTER")
                    for argument in arguments[1:]
                )
                if contains_crossfilter:
                    if not arguments[1:] or any(
                        argument[0] != "call" or argument[1] != "CROSSFILTER"
                        for argument in arguments[1:]
                    ):
                        raise MeasureError(
                            "CROSSFILTER must be the only kind of CALCULATE filter argument in this local subset."
                        )
                    for modifier in arguments[1:]:
                        _validate_crossfilter_call(modifier)
                    return ("call", function, tuple(arguments))
                valid_time_filter = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] in _TIME_FILTER_FUNCTIONS
                )
                valid_table_filter = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] == "FILTER"
                )
                valid_removefilters = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] == "REMOVEFILTERS"
                )
                valid_all = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] == "ALL"
                )
                valid_allnoblankrow = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] == "ALLNOBLANKROW"
                )
                valid_allexcept = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] == "ALLEXCEPT"
                )
                valid_allselected = (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1] == "ALLSELECTED"
                )
                contains_filter_clear = {
                    clear_function
                    for clear_function in {
                        "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED"
                    }
                    if any(
                        _contains_function_call(argument, clear_function)
                        for argument in arguments[1:]
                    )
                }
                if contains_filter_clear and not (
                    valid_removefilters or valid_all or valid_allnoblankrow or valid_allexcept or valid_allselected
                ):
                    clear_function = sorted(contains_filter_clear)[0]
                    raise MeasureError(
                        f"{clear_function} must be the only CALCULATE filter argument in this local subset."
                    )
                if valid_removefilters or valid_all or valid_allnoblankrow or valid_allexcept or valid_allselected:
                    if valid_allexcept:
                        _validate_allexcept_call(arguments[1])
                    else:
                        _validate_filter_clear_call(arguments[1], arguments[1][1])
                    if valid_allnoblankrow and not arguments[1][2]:
                        raise MeasureError(
                            "ALLNOBLANKROW needs a table or column argument."
                        )
                    return ("call", function, tuple(arguments))
                contains_table_filter = any(
                    _contains_function_call(argument, "FILTER")
                    for argument in arguments[1:]
                )
                if contains_table_filter and not valid_table_filter:
                    raise MeasureError(
                        "A table-valued FILTER must be the only CALCULATE filter argument."
                    )
                contains_time_filter = any(
                    argument[0] == "call" and argument[1] in _TIME_FILTER_FUNCTIONS
                    for argument in arguments[1:]
                )
                if contains_time_filter and not valid_time_filter:
                    raise MeasureError(
                        "Time-intelligence filters cannot be combined with other "
                        "CALCULATE filters yet."
                    )
                if not valid_time_filter and not valid_table_filter:
                    for filter_argument in arguments[1:]:
                        predicate, _keep = _calculate_filter_argument(filter_argument)
                        _calculate_boolean_filter_column(predicate)
            return ("call", function, tuple(arguments))
        raise MeasureError(f"Unexpected token {token.value!r}; expected a number, measure, or function.")

    def _peek(self) -> str | None:
        return self.tokens[self.index].kind if self.index < len(self.tokens) else None

    def _take(self) -> Token:
        if self.index >= len(self.tokens):
            raise MeasureError("The DAX expression ends unexpectedly.")
        token = self.tokens[self.index]
        self.index += 1
        return token

    def _expect(self, kind: str) -> None:
        token = self._take()
        if token.kind != kind:
            raise MeasureError(f"Expected {kind!r}, found {token.value!r}.")


def parse_expression(expression: str) -> tuple[Any, ...]:
    """Parse one supported DAX expression into a safe internal tree."""
    return _Parser(tokenize(expression)).parse()


def _contains_table_call(node: Any) -> bool:
    if not isinstance(node, tuple) or not node:
        return False
    return (
        node[0] == "table_call"
        or (
            node[0] == "call"
            and node[1] in {
                "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH",
                "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN", "DATESINPERIOD", "FILTER", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED",
            }
        )
        or any(
            _contains_table_call(child) for child in node[1:]
        )
    )


def _is_supported_time_filter_calculate(node: Any) -> bool:
    if not (
        isinstance(node, tuple)
        and len(node) == 3
        and node[0] == "call"
        and node[1] == "CALCULATE"
        and len(node[2]) == 2
        and node[2][1][0] == "call"
        and node[2][1][1] in {
            "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH",
            "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN", "DATESINPERIOD",
        }
    ):
        return False
    return not _contains_table_call(node[2][0])


def _is_supported_table_filter_calculate(node: Any) -> bool:
    if not (
        isinstance(node, tuple)
        and len(node) == 3
        and node[0] == "call"
        and node[1] == "CALCULATE"
        and len(node[2]) == 2
        and node[2][1][0] == "call"
        and node[2][1][1] == "FILTER"
    ):
        return False
    return not _contains_table_call(node[2][0])


def normalize_calculated_table_expression(
    expression: Any,
    source_table: Any,
    headers: Iterable[str] | None = None,
) -> dict[str, str]:
    """Validate the local one-column DISTINCT calculated-table subset."""
    if not isinstance(expression, str) or not expression.strip():
        raise MeasureError("Enter a calculated-table expression.")
    if not isinstance(source_table, str) or not source_table.strip():
        raise MeasureError("Choose a source table for the calculated table.")
    clean_expression = expression.strip()
    node = parse_expression(clean_expression)
    if node[0] != "table_call" or node[1] != "DISTINCT":
        raise MeasureError(
            "Calculated tables currently support DISTINCT('Table'[Column]) expressions."
        )
    reference = node[2]
    if reference[0] != "reference" or not reference[1]:
        raise MeasureError("Use a qualified source column, such as DISTINCT('Sales'[Region]).")
    if reference[1].casefold() != source_table.strip().casefold():
        raise MeasureError(
            f"The expression must reference the selected source table {source_table!r}."
        )
    if headers is not None:
        columns_by_key = {str(header).casefold(): str(header) for header in headers}
        actual = columns_by_key.get(reference[2].casefold())
        if actual is None:
            raise MeasureError(f"Column {reference[2]!r} does not exist in {source_table!r}.")
        if "]" in actual:
            raise MeasureError("Column names containing ']' are not supported in this DAX subset.")
        return {"expression": clean_expression, "source_table": source_table.strip(), "column": actual}
    return {
        "expression": clean_expression,
        "source_table": source_table.strip(),
        "column": reference[2],
    }


def evaluate_calculated_table(
    expression: Any,
    source_candidate: Any,
    source_table: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Materialize DISTINCT over one loaded column, preserving first-seen order."""
    definition = normalize_calculated_table_expression(
        expression, source_table, source_candidate.headers
    )
    column = definition["column"]
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for source_row in source_candidate.rows:
        value = source_row.get(column)
        normalized = "" if value is None else str(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        rows.append({column: normalized})
    return [column], rows


def normalize_calculated_column(name: Any, expression: Any) -> dict[str, str]:
    """Validate one local calculated-column definition."""
    if not isinstance(name, str) or not name.strip():
        raise MeasureError("Enter a calculated column name.")
    clean_name = name.strip()
    if len(clean_name) > 120 or any(char in clean_name for char in "[]\r\n"):
        raise MeasureError(
            "Calculated column names must be 1–120 characters and cannot contain brackets or line breaks."
        )
    if not isinstance(expression, str) or not expression.strip():
        raise MeasureError("Enter a DAX expression for the calculated column.")
    clean_expression = expression.strip()
    parsed_expression = parse_expression(clean_expression)
    if any(
        _contains_function_call(parsed_expression, function)
        for function in ("USERELATIONSHIP", "CROSSFILTER")
    ):
        raise MeasureError(
            "Relationship filter modifiers are supported only for measures in this local subset."
        )
    if _contains_table_call(parsed_expression):
        raise MeasureError("Table-valued functions are not supported in calculated columns.")
    return {"name": clean_name, "expression": clean_expression}


def validate_calculated_columns(value: Any) -> list[dict[str, str]]:
    """Return the canonical persisted shape for a table's calculated columns."""
    if not isinstance(value, list) or len(value) > MAX_CALCULATED_COLUMNS:
        raise MeasureError(
            f"A table can contain at most {MAX_CALCULATED_COLUMNS} calculated columns."
        )
    result: list[dict[str, str]] = []
    names: set[str] = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict) or set(item) != {"name", "expression"}:
            raise MeasureError(
                f"Calculated column {index} must contain only name and expression fields."
            )
        column = normalize_calculated_column(item["name"], item["expression"])
        key = column["name"].casefold()
        if key in names:
            raise MeasureError(f"Calculated column {column['name']!r} is duplicated.")
        names.add(key)
        result.append(column)
    return result


def evaluate_calculated_columns(
    definitions: Iterable[dict[str, str]],
    rows: list[dict[str, Any]],
    headers: list[str],
    table_name: str = "",
) -> tuple[list[str], list[dict[str, Any]], dict[str, str]]:
    """Materialize a table's numeric/boolean row expressions in definition order."""
    columns = validate_calculated_columns(list(definitions))
    output_headers = list(headers)
    output_rows = [dict(row) for row in rows]
    output_types: dict[str, str] = {}

    for definition in columns:
        name = definition["name"]
        header_by_key = {header.casefold(): header for header in output_headers}
        if name.casefold() in header_by_key:
            raise MeasureError(f"A column named {name!r} already exists in table {table_name!r}.")
        expression = parse_expression(definition["expression"])
        result_values: list[Decimal | bool | None] = []

    
        def evaluate_with_context_transition(
            node: tuple[Any, ...],
            iterated_table: dict[str, Any],
            row: dict[str, Any],
        ) -> Decimal | bool | None:
        '''Create a filter context mimicking the current row context and evaluate.'''
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids

        table_id = iterated_table["id"]
        allowed_rows = frozenset(
            row_index
            for row_index, iterate_row in enumerate(iterated_table["rows"], 1)
            if all(
                str(iterate_row.get(header, "")).strip() == str(row.get(header, "")).strip()
                for header in iterated_table["headers"]
            )
        )
        
        updated_by_id = {key: dict(value) for key, value in evaluation_contexts_by_id.items()}
        target_context = updated_by_id.get(table_id)
        if target_context is None:
            target_context = dict(iterated_table)
            updated_by_id[table_id] = target_context
            
        updated_column_rows = dict(target_context.get("filter_column_rows", {}))
        for header in iterated_table["headers"]:
            updated_column_rows[header] = allowed_rows
            
        target_context["filter_column_rows"] = updated_column_rows
        target_context["filter_context_complete"] = True
        
        updated_filter_roots = evaluation_filter_ids | {table_id}
        
        filtered_rows_by_id = dict(rows_by_table_id)
        filtered_rows_by_id[table_id] = propagate_relationship_filters(
            updated_by_id, relationships, updated_filter_roots, False, None
        )

        previous_rows = rows_by_table_id
        previous_context = current_context
        previous_contexts = evaluation_contexts_by_id
        previous_filter_ids = evaluation_filter_ids
        context_sequence += 1
        current_context = context_sequence
        evaluation_contexts_by_id = updated_by_id
        evaluation_filter_ids = updated_filter_roots
        rows_by_table_id = filtered_rows_by_id
        try:
            return evaluate(node)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids

    def evaluate(
            node: tuple[Any, ...], row: dict[str, Any], row_index: int
        ) -> Decimal | bool | None:
            kind = node[0]
            if kind == "number":
                return node[1]
            if kind == "boolean":
