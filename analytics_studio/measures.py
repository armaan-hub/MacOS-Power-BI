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
            for filter_argument in arguments[1:]:
                if filter_argument[0] == "call" and filter_argument[1] in _TIME_FILTER_FUNCTIONS:
                    _validate_literal_positions(filter_argument)
                else:
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
                if not valid_time_filter and not valid_table_filter:
                    for filter_argument in arguments[1:]:
                        if filter_argument[0] == "call" and filter_argument[1] in _TIME_FILTER_FUNCTIONS:
                            continue
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
        and len(node[2]) >= 2
    ):
        return False
    # Verify that there's at least one time-filter argument
    has_time_filter = any(
        arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS
        for arg in node[2][1:]
    )
    if not has_time_filter:
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

    
        def evaluate(
            node: tuple[Any, ...], row: dict[str, Any], row_index: int
        ) -> Decimal | bool | None:
            kind = node[0]
            if kind == "number":
                return node[1]
            if kind == "boolean":
                return node[1]
            if kind == "table":
                raise MeasureError(
                    "Table names are not supported in calculated-column expressions."
                )
            if kind == "reference":
                _, table, column = node
                if table and table.casefold() != table_name.casefold():
                    raise MeasureError(
                        "A calculated column can reference columns from its own table only."
                    )
                actual = header_by_key.get(column.casefold())
                if actual is None:
                    raise MeasureError(
                        f"Column {column!r} does not exist in table {table_name!r}."
                    )
                raw = row.get(actual)
                value = "" if raw is None else str(raw).strip()
                if not value:
                    return None
                if value.casefold() in {"true", "false"}:
                    return value.casefold() == "true"
                try:
                    number = Decimal(value.replace(",", ""))
                except (DecimalException, ValueError) as exc:
                    raise MeasureError(
                        f"Column {actual!r} contains a non-numeric value at row {row_index}."
                    ) from exc
                if not number.is_finite():
                    raise MeasureError(f"Column {actual!r} contains a non-finite number.")
                return number
            if kind == "unary":
                value = as_number(evaluate(node[2], row, row_index))
                return value if node[1] == "+" else -value
            if kind == "binary":
                left = as_number(evaluate(node[2], row, row_index))
                right = as_number(evaluate(node[3], row, row_index))
                if node[1] == "+":
                    return left + right
                if node[1] == "-":
                    return left - right
                if node[1] == "*":
                    return left * right
                if right == 0:
                    raise MeasureError(
                        f"Calculated column {name!r} divides by zero at row {row_index}."
                    )
                return left / right
            if kind == "logical":
                left = as_boolean(evaluate(node[2], row, row_index))
                if node[1] == "&&":
                    return left and as_boolean(evaluate(node[3], row, row_index))
                return left or as_boolean(evaluate(node[3], row, row_index))
            if kind == "comparison":
                left = evaluate(node[2], row, row_index)
                right = evaluate(node[3], row, row_index)
                if isinstance(left, bool) and isinstance(right, bool):
                    if node[1] == "=":
                        return left == right
                    if node[1] == "<>":
                        return left != right
                    raise MeasureError("True/False values support only equality comparisons.")
                left_number, right_number = as_number(left), as_number(right)
                return {
                    "=": left_number == right_number,
                    "<>": left_number != right_number,
                    "<": left_number < right_number,
                    "<=": left_number <= right_number,
                    ">": left_number > right_number,
                    ">=": left_number >= right_number,
                }[node[1]]
            _, function, arguments = node
            if function == "IF":
                return (
                    evaluate(arguments[1], row, row_index)
                    if as_boolean(evaluate(arguments[0], row, row_index))
                    else evaluate(arguments[2], row, row_index)
                )
            if function in {"AND", "OR"}:
                left = as_boolean(evaluate(arguments[0], row, row_index))
                if function == "AND":
                    return left and as_boolean(evaluate(arguments[1], row, row_index))
                return left or as_boolean(evaluate(arguments[1], row, row_index))
            if function == "NOT":
                return not as_boolean(evaluate(arguments[0], row, row_index))
            if function == "ABS":
                return abs(as_number(evaluate(arguments[0], row, row_index)))
            if function == "ROUND":
                value = as_number(evaluate(arguments[0], row, row_index))
                precision = as_number(evaluate(arguments[1], row, row_index))
                if precision != precision.to_integral_value() or abs(precision) > 28:
                    raise MeasureError("ROUND digits must be a whole number from -28 to 28.")
                quantum = Decimal(1).scaleb(-int(precision))
                return value.quantize(quantum, rounding=ROUND_HALF_UP)
            raise MeasureError(
                f"{function} is not supported in calculated-column expressions."
            )

        def as_number(value: Decimal | bool | None) -> Decimal:
            if value is None:
                return Decimal(0)
            if not isinstance(value, Decimal):
                raise MeasureError("This calculated-column expression needs a numeric value.")
            return value

        def as_boolean(value: Decimal | bool | None) -> bool:
            if value is None:
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, Decimal):
                return value != 0
            raise MeasureError("This calculated-column expression needs a logical value.")

        for row_index, row in enumerate(output_rows, 1):
            try:
                result_values.append(evaluate(expression, row, row_index))
            except (DecimalException, OverflowError) as exc:
                raise MeasureError(
                    f"Calculated column {name!r} is outside the supported numeric range at row {row_index}."
                ) from exc

        value_kinds = {"boolean" if isinstance(value, bool) else "numeric"
                       for value in result_values if value is not None}
        if len(value_kinds) > 1:
            raise MeasureError(
                f"Calculated column {name!r} returns mixed numeric and True/False values."
            )
        column_type = "boolean" if value_kinds == {"boolean"} else "decimal_number"
        for row, value in zip(output_rows, result_values):
            if value is None:
                row[name] = ""
            elif isinstance(value, bool):
                row[name] = "True" if value else "False"
            else:
                row[name] = str(value)
        output_headers.append(name)
        output_types[name] = column_type

    return output_headers, output_rows, output_types


def normalize_measure(name: Any, expression: Any) -> dict[str, str]:
    """Validate a persisted measure and return its canonical JSON-safe shape."""
    if not isinstance(name, str) or not name.strip():
        raise MeasureError("Enter a measure name.")
    clean_name = name.strip()
    if len(clean_name) > 120 or any(char in clean_name for char in "[]\r\n"):
        raise MeasureError("Measure names must be 1–120 characters and cannot contain brackets or line breaks.")
    if not isinstance(expression, str):
        raise MeasureError("A measure expression must be text.")
    clean_expression = expression.strip()
    # Accept a complete DAX assignment in the expression box as a convenience.
    assignment = _FORMULA_ASSIGNMENT.match(clean_expression)
    if assignment is not None:
        assignment_name = (assignment.group("bracketed") or assignment.group("plain") or "").strip()
        assigned_expression = clean_expression[assignment.end():].strip()
        if not assignment_name or not assigned_expression:
            raise MeasureError("Use the form Measure Name = expression.")
        if name.strip() and name.strip() != "Measure":
            clean_name = name.strip()
            if clean_name.casefold() != assignment_name.casefold():
                raise MeasureError("The formula name must match the Measure name field.")
        else:
            clean_name = assignment_name
        clean_expression = assigned_expression.strip()
    parsed_expression = parse_expression(clean_expression)
    if (
        _contains_table_call(parsed_expression)
        and not _is_supported_time_filter_calculate(parsed_expression)
        and not _is_supported_table_filter_calculate(parsed_expression)
        and not _has_supported_all_usage(parsed_expression)
    ):
        raise MeasureError("Table-valued functions are not supported in measure expressions.")
    return {"name": clean_name, "expression": clean_expression}


def validate_measures(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_MEASURES:
        raise MeasureError(f"A model can contain at most {MAX_MEASURES} measures.")
    result = []
    names: set[str] = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict) or set(item) != {"name", "expression"}:
            raise MeasureError(f"Measure {index} must contain only name and expression fields.")
        measure = normalize_measure(item["name"], item["expression"])
        key = measure["name"].casefold()
        if key in names:
            raise MeasureError(f"Measure {measure['name']!r} is duplicated.")
        names.add(key)
        result.append(measure)
    return result


def _parse_measure_date(value: Any, column: str, row_index: int) -> date | None:
    """Read an ISO Date/DateTime model value for a time-intelligence measure."""
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        parsed_date = date.fromisoformat(text)
        if parsed_date.isoformat() == text:
            return parsed_date
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise MeasureError(
            f"Marked date column {column!r} contains an invalid date at row {row_index}."
        ) from exc


def _dateadd_dates(
    selected_dates: Iterable[date], intervals: int, interval: str
) -> set[date]:
    """Shift a contiguous classic date-column selection by DATEADD intervals."""
    source_dates = sorted(set(selected_dates))
    unit = interval.upper()
    if unit not in {"YEAR", "QUARTER", "MONTH", "DAY"}:
        raise MeasureError("DATEADD date-column intervals support YEAR, QUARTER, MONTH, or DAY.")
    if not source_dates:
        return set()
    if (
        len(source_dates) > 1
        and (source_dates[-1] - source_dates[0]).days + 1 != len(source_dates)
    ):
        raise MeasureError(
            "DATEADD requires the current date-column selection to be contiguous."
        )

    if unit == "DAY":
        try:
            return {value + timedelta(days=intervals) for value in source_dates}
        except OverflowError as exc:
            raise MeasureError("DATEADD shifted dates outside the supported date range.") from exc

    month_shift = intervals * {"MONTH": 1, "QUARTER": 3, "YEAR": 12}[unit]

    def shift_month(value: date) -> date:
        target_index = value.year * 12 + value.month - 1 + month_shift
        target_year, zero_based_month = divmod(target_index, 12)
        target_month = zero_based_month + 1
        if not 1 <= target_year <= 9999:
            raise MeasureError("DATEADD shifted dates outside the supported date range.")
        target_day = min(value.day, monthrange(target_year, target_month)[1])
        return date(target_year, target_month, target_day)

    try:
        shifted = {shift_month(value) for value in source_dates}
    except (OverflowError, ValueError) as exc:
        raise MeasureError("DATEADD shifted dates outside the supported date range.") from exc

    # Classic date-column syntax extends to month end when the selection
    # includes the final two days of its source month.
    if unit == "MONTH" and len(source_dates) >= 2:
        source_end = source_dates[-1]
        source_month_end = monthrange(source_end.year, source_end.month)[1]
        if (
            source_end.day == source_month_end
            and source_dates[-2] == source_end - timedelta(days=1)
        ):
            shifted_end = shift_month(source_end)
            destination_end = date(
                shifted_end.year,
                shifted_end.month,
                monthrange(shifted_end.year, shifted_end.month)[1],
            )
            if shifted_end < destination_end:
                for offset in range(1, (destination_end - shifted_end).days + 1):
                    shifted.add(shifted_end + timedelta(days=offset))
    return shifted


def _sameperiodlastyear_dates(selected_dates: Iterable[date]) -> set[date]:
    """Shift a classic date-column selection one year back with leap extension."""
    source_dates = sorted(set(selected_dates))
    if len(source_dates) > 1 and (source_dates[-1] - source_dates[0]).days + 1 != len(source_dates):
        raise MeasureError(
            "SAMEPERIODLASTYEAR requires the current date-column selection to be contiguous."
        )
    shifted = _dateadd_dates(source_dates, -1, "YEAR")
    if len(source_dates) < 2:
        return shifted

    source_end = source_dates[-1]
    source_month_end = monthrange(source_end.year, source_end.month)[1]
    if (
        source_end.day != source_month_end
        or source_dates[-2] != source_end - timedelta(days=1)
    ):
        return shifted

    shifted_end = date(
        source_end.year - 1,
        source_end.month,
        min(source_end.day, monthrange(source_end.year - 1, source_end.month)[1]),
    )
    destination_end = date(
        shifted_end.year,
        shifted_end.month,
        monthrange(shifted_end.year, shifted_end.month)[1],
    )
    if shifted_end < destination_end:
        for offset in range(1, (destination_end - shifted_end).days + 1):
            shifted.add(shifted_end + timedelta(days=offset))
    return shifted


def evaluate_measures(
    measures: Iterable[dict[str, str]],
    rows: list[dict[str, Any]],
    headers: list[str],
    table_name: str = "",
    *,
    measure_names: Iterable[str] | None = None,
    table_context: Iterable[dict[str, Any]] | None = None,
    relationships: Iterable[dict[str, Any]] = (),
    filter_table_ids: Iterable[str] = (),
    active_table_id: str | None = None,
) -> dict[str, Decimal]:
    """Evaluate measures over local tables and their active relationship paths."""
    definitions = validate_measures(list(measures))
    by_name = {item["name"].casefold(): item for item in definitions}
    parsed = {item["name"].casefold(): parse_expression(item["expression"]) for item in definitions}

    contexts_by_id: dict[str, dict[str, Any]] = {}
    if table_context is not None:
        for item in table_context:
            if not isinstance(item, dict):
                raise MeasureError("Each loaded table needs an ID, name, columns, and rows.")
            table_id = item.get("id")
            if not isinstance(table_id, str) or not table_id:
                raise MeasureError("A loaded table is missing its model ID.")
            if table_id in contexts_by_id:
                raise MeasureError("Loaded model table IDs must be unique.")
            table_headers = item.get("headers")
            table_rows = item.get("rows")
            if not isinstance(table_headers, list) or not isinstance(table_rows, list):
                raise MeasureError("A loaded table is missing its columns or rows.")
            normalized_headers = [str(header) for header in table_headers]
            header_by_key = {
                header.casefold(): header for header in normalized_headers
            }
            supplied_column_rows = item.get("filter_column_rows", {})
            if not isinstance(supplied_column_rows, dict):
                raise MeasureError(
                    f"Loaded table {item.get('name', table_id)!r} has an invalid per-column filter context."
                )
            filter_column_rows: dict[str, frozenset[int]] = {}
            for column, indexes in supplied_column_rows.items():
                actual_column = header_by_key.get(str(column).casefold())
                if actual_column is None:
                    raise MeasureError(
                        f"Loaded table {item.get('name', table_id)!r} has filter context for an unavailable column."
                    )
                if (
                    not isinstance(indexes, (list, tuple, set, frozenset))
                    or any(type(index) is not int or not 0 <= index < len(table_rows) for index in indexes)
                ):
                    raise MeasureError(
                        f"Loaded table {item.get('name', table_id)!r} has invalid per-column filter rows."
                    )
                filter_column_rows[actual_column] = frozenset(indexes)
            supplied_blank_allowed = item.get("filter_column_blank_allowed", {})
            if not isinstance(supplied_blank_allowed, dict):
                raise MeasureError(
                    f"Loaded table {item.get('name', table_id)!r} has invalid blank-filter provenance."
                )
            filter_column_blank_allowed: dict[str, bool] = {}
            for column, allowed in supplied_blank_allowed.items():
                actual_column = header_by_key.get(str(column).casefold())
                if actual_column is None or type(allowed) is not bool:
                    raise MeasureError(
                        f"Loaded table {item.get('name', table_id)!r} has invalid blank-filter provenance."
                    )
                filter_column_blank_allowed[actual_column] = allowed
            supplied_table_rows = item.get("filter_table_rows")
            if supplied_table_rows is not None and (
                not isinstance(supplied_table_rows, (list, tuple, set, frozenset))
                or any(
                    type(index) is not int or not 0 <= index < len(table_rows)
                    for index in supplied_table_rows
                )
            ):
                raise MeasureError(
                    f"Loaded table {item.get('name', table_id)!r} has invalid table-filter rows."
                )
            filter_context_complete = item.get("filter_context_complete", False)
            if type(filter_context_complete) is not bool:
                raise MeasureError(
                    f"Loaded table {item.get('name', table_id)!r} has an invalid filter-context marker."
                )
            contexts_by_id[table_id] = {
                "id": table_id,
                "name": str(item.get("name") or table_id),
                "headers": normalized_headers,
                "rows": list(table_rows),
                "column_types": dict(item.get("column_types", {})),
                "date_column": str(item.get("date_column") or ""),
                "filter_column_rows": filter_column_rows,
                "filter_column_blank_allowed": filter_column_blank_allowed,
                "filter_context_complete": filter_context_complete,
                **({"filter_rows": list(item["filter_rows"])} if "filter_rows" in item else {}),
                **({"filter_table_rows": frozenset(supplied_table_rows)}
                   if supplied_table_rows is not None else {}),
            }

    active_context = contexts_by_id.get(active_table_id or "")
    if active_context is None and table_name:
        active_context = next(
            (item for item in contexts_by_id.values()
             if item["name"].casefold() == table_name.casefold()),
            None,
        )
    if active_context is None and len(contexts_by_id) == 1:
        active_context = next(iter(contexts_by_id.values()))
    if active_context is None:
        synthetic_id = active_table_id or "__active_table__"
        if synthetic_id in contexts_by_id:
            raise MeasureError("The active table ID does not identify the selected table.")
        active_context = {
            "id": synthetic_id,
            "name": table_name or "Active table",
            "headers": list(headers),
            "rows": list(rows),
            "column_types": {},
            "filter_column_rows": {},
            "filter_context_complete": False,
        }
        contexts_by_id[synthetic_id] = active_context
    active_table_id = active_context["id"]
    filter_ids = set(filter_table_ids)
    if active_table_id in filter_ids and "filter_rows" not in active_context:
        active_context["filter_rows"] = list(rows)
    evaluation_contexts_by_id = contexts_by_id
    evaluation_filter_ids = set(filter_ids)
    relationship_definitions = list(relationships)

    table_names: dict[str, list[dict[str, Any]]] = {}
    for context in contexts_by_id.values():
        table_names.setdefault(context["name"].casefold(), []).append(context)

    try:
        rows_by_table_id = propagate_relationship_filters(
            list(contexts_by_id.values()),
            relationship_definitions,
            filter_ids,
        )
    except RelationshipError as exc:
        raise MeasureError(f"Could not apply model relationships: {exc}") from exc
    try:
        unknown_member_ids = unknown_member_table_ids(
            list(contexts_by_id.values()), relationship_definitions
        )
    except (RelationshipError, DecimalException) as exc:
        raise MeasureError(f"Could not inspect model relationships: {exc}") from exc
    unknown_member_exclusions: dict[str, set[str] | None] = {}

    value_cache: dict[tuple[str, int], Decimal] = {}
    resolving: set[str] = set()
    context_sequence = 0
    current_context = 0

    def resolve_table_context(table: str) -> dict[str, Any]:
        if not table:
            return evaluation_contexts_by_id.get(active_context["id"], active_context)
        matches = table_names.get(table.casefold(), [])
        if not matches:
            raise MeasureError(f"Table {table!r} is not loaded in the model.")
        if len(matches) > 1:
            raise MeasureError(f"Table name {table!r} is ambiguous in the model.")
        return evaluation_contexts_by_id.get(matches[0]["id"], matches[0])

    def resolve_table(table: str, column: str) -> tuple[dict[str, Any], str]:
        context = resolve_table_context(table)
        header_by_key = {header.casefold(): header for header in context["headers"]}
        actual = header_by_key.get(column.casefold())
        if actual is None:
            raise MeasureError(
                f"Column {column!r} does not exist in table {context['name']!r}."
            )
        return context, actual

    def rows_after_clearing_columns(
        source_context: dict[str, Any],
        columns_to_clear: set[str],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        set[str],
    ]:
        """Recompute a table's visible rows after removing only selected columns."""
        table_id = source_context["id"]
        updated_contexts = [
            dict(context) for context in evaluation_contexts_by_id.values()
        ]
        updated_by_id = {context["id"]: context for context in updated_contexts}
        updated = updated_by_id[table_id]
        if "filter_table_rows" in updated:
            raise MeasureError(
                "ALL column table expressions cannot clear columns from an opaque FILTER rowset."
            )
        existing_column_rows = updated.get("filter_column_rows", {})
        has_direct_filter_state = (
            table_id in evaluation_filter_ids
            or "filter_rows" in updated
            or bool(existing_column_rows)
        )
        if has_direct_filter_state and not updated.get("filter_context_complete", False):
            raise MeasureError(
                "ALL column table expressions need complete per-column filter context."
            )
        remaining_column_rows = {
            column: frozenset(indexes)
            for column, indexes in existing_column_rows.items()
            if column.casefold() not in columns_to_clear
        }
        updated["filter_column_rows"] = remaining_column_rows
        updated["filter_column_blank_allowed"] = {
            column: allowed
            for column, allowed in updated.get(
                "filter_column_blank_allowed", {}
            ).items()
            if column.casefold() not in columns_to_clear
        }
        updated["filter_context_complete"] = True
        updated_filter_roots = set(evaluation_filter_ids)
        if remaining_column_rows:
            updated["filter_rows"] = [
                row
                for row_index, row in enumerate(updated["rows"])
                if all(
                    row_index in indexes
                    for indexes in remaining_column_rows.values()
                )
            ]
            updated_filter_roots.add(table_id)
        else:
            updated.pop("filter_rows", None)
            updated_filter_roots.discard(table_id)
        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(f"Could not apply ALL column filters: {exc}") from exc
        return (
            filtered_rows_by_id[table_id],
            updated_by_id,
            updated_filter_roots,
        )

    def unknown_member_passes_remaining_filters(
        source_context: dict[str, Any],
        contexts_by_id: dict[str, dict[str, Any]],
        filter_roots: set[str],
        columns_being_cleared: set[str] | None = None,
    ) -> bool:
        """Check whether the virtual blank survives direct and related filters."""
        source_id = source_context["id"]
        if source_id not in unknown_member_ids:
            return False
        current_source_context = contexts_by_id[source_id]
        if "filter_table_rows" in current_source_context:
            # This bounded FILTER rowset is opaque and contains only the
            # physical rows evaluated by its predicate. Do not infer that the
            # generated unknown member survived it.
            return False
        if source_id in unknown_member_exclusions:
            excluded_columns = unknown_member_exclusions[source_id]
            if excluded_columns is None or excluded_columns - (columns_being_cleared or set()):
                return False
        blank_allowed = current_source_context.get(
            "filter_column_blank_allowed", {}
        )
        for column in current_source_context.get("filter_column_rows", {}):
            if column not in blank_allowed:
                raise MeasureError(
                    "ALL column table expressions need blank-filter provenance when a virtual unknown member is present."
                )
            if not blank_allowed[column]:
                return False

        independent_filter_roots = filter_roots - {source_context["id"]}
        visible_rows_by_id: dict[str, list[dict[str, Any]]] = {}
        if independent_filter_roots:
            independent_contexts = [
                context
                for table_id, context in contexts_by_id.items()
                if table_id != source_context["id"]
            ]
            independent_relationships = [
                relationship
                for relationship in relationship_definitions
                if not (
                    isinstance(relationship, dict)
                    and source_context["id"]
                    in {
                        str(relationship.get("from_table_id", "")),
                        str(relationship.get("to_table_id", "")),
                    }
                )
            ]
            try:
                propagated_without_target = propagate_relationship_filters(
                    independent_contexts,
                    independent_relationships,
                    independent_filter_roots,
                )
            except RelationshipError as exc:
                raise MeasureError(
                    f"Could not apply relationship filters to the virtual blank member: {exc}"
                ) from exc
            visible_rows_by_id = propagated_without_target

        try:
            context_unknown_members = unknown_member_table_ids(
                list(contexts_by_id.values()),
                relationship_definitions,
                visible_rows_by_id,
            )
        except (RelationshipError, DecimalException) as exc:
            raise MeasureError(
                f"Could not inspect model relationships: {exc}"
            ) from exc
        if source_context["id"] not in context_unknown_members:
            return False

        reachable_table_ids = set(independent_filter_roots)
        filter_edges: dict[str, set[str]] = {}
        for relationship in relationship_definitions:
            if (
                not isinstance(relationship, dict)
                or type(relationship.get("relationship_version")) is not int
                or relationship.get("relationship_version") != 1
                or not relationship.get("is_active")
            ):
                continue
            from_id = str(relationship.get("from_table_id", ""))
            to_id = str(relationship.get("to_table_id", ""))
            if (
                from_id == source_context["id"]
                or to_id == source_context["id"]
                or from_id not in contexts_by_id
                or to_id not in contexts_by_id
            ):
                continue
            directions = relationship_filter_directions(relationship)
            if "from_to" in directions:
                filter_edges.setdefault(from_id, set()).add(to_id)
            if "to_from" in directions:
                filter_edges.setdefault(to_id, set()).add(from_id)
        pending = list(reachable_table_ids)
        while pending:
            table_id = pending.pop()
            for target_id in filter_edges.get(table_id, set()):
                if target_id not in reachable_table_ids:
                    reachable_table_ids.add(target_id)
                    pending.append(target_id)

        def incoming_source(
            relationship: dict[str, Any], target_id: str
        ) -> tuple[str, str] | None:
            from_id = str(relationship.get("from_table_id", ""))
            to_id = str(relationship.get("to_table_id", ""))
            directions = relationship_filter_directions(relationship)
            if "to_from" in directions and target_id == from_id:
                return to_id, str(relationship.get("to_column", ""))
            if "from_to" in directions and target_id == to_id:
                return from_id, str(relationship.get("from_column", ""))
            return None

        for relationship in relationship_definitions:
            if not isinstance(relationship, dict) or not relationship.get("is_active"):
                continue
            source = incoming_source(relationship, source_context["id"])
            if source is None:
                continue
            source_id, source_column = source
            if source_id not in reachable_table_ids:
                continue
            try:
                link_unknown_members = unknown_member_table_ids(
                    list(contexts_by_id.values()),
                    [relationship],
                    visible_rows_by_id,
                )
            except (RelationshipError, DecimalException) as exc:
                raise MeasureError(
                    f"Could not inspect model relationships: {exc}"
                ) from exc
            if source_context["id"] in link_unknown_members:
                continue
            source_table = contexts_by_id.get(source_id)
            if source_table is None:
                continue
            source_rows = visible_rows_by_id.get(
                source_id, source_table["rows"]
            )
            if not any(
                row.get(source_column) is None
                or str(row.get(source_column, "")) == ""
                for row in source_rows
            ):
                return False
        return True

    def all_table_value(
        expression: tuple[Any, ...],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Materialize supported ALL-family table and column forms."""
        arguments = expression[2]
        function = expression[1]
        if len(arguments) == 1 and arguments[0][0] == "table":
            source_context = resolve_table_context(str(arguments[0][1]))
            output_headers = list(source_context["headers"])
            if function == "ALLSELECTED":
                output_rows = list(rows_by_table_id[source_context["id"]])
                current_context = evaluation_contexts_by_id.get(
                    source_context["id"], source_context
                )
                if (
                    source_context["id"] in unknown_member_ids
                    and source_context["id"] not in unknown_member_exclusions
                    and unknown_member_passes_remaining_filters(
                        current_context,
                        evaluation_contexts_by_id,
                        evaluation_filter_ids,
                    )
                ):
                    output_rows.append({header: "" for header in output_headers})
            else:
                output_rows = list(source_context["rows"])
                if function == "ALL" and source_context["id"] in unknown_member_ids:
                    output_rows.append({header: "" for header in output_headers})
        else:
            resolved_columns = [
                resolve_table(reference[1], reference[2])
                for reference in arguments
            ]
            source_context = resolved_columns[0][0]
            if any(context["id"] != source_context["id"] for context, _ in resolved_columns):
                raise MeasureError(
                    f"{function} column arguments must resolve to one loaded table."
                )
            output_headers = [column for _context, column in resolved_columns]
            if function == "ALLSELECTED":
                source_rows = list(rows_by_table_id[source_context["id"]])
                current_context = evaluation_contexts_by_id.get(
                    source_context["id"], source_context
                )
                if (
                    source_context["id"] in unknown_member_ids
                    and source_context["id"] not in unknown_member_exclusions
                    and unknown_member_passes_remaining_filters(
                        current_context,
                        evaluation_contexts_by_id,
                        evaluation_filter_ids,
                    )
                ):
                    source_rows.append({header: "" for header in source_context["headers"]})
            else:
                (
                    source_rows,
                    contexts_after_clear,
                    filter_roots_after_clear,
                ) = rows_after_clearing_columns(
                    source_context,
                    {column.casefold() for column in output_headers},
                )
                if function == "ALL" and unknown_member_passes_remaining_filters(
                    source_context,
                    contexts_after_clear,
                    filter_roots_after_clear,
                    {column.casefold() for column in output_headers},
                ):
                    source_rows.append({header: "" for header in source_context["headers"]})

            def value_key(value: Any, column: str) -> tuple[str, Any]:
                if value is None or str(value) == "":
                    return ("blank", "")
                text = str(value)
                column_type = str(source_context.get("column_types", {}).get(column, "text"))
                if column_type in {"whole_number", "decimal_number"}:
                    try:
                        number = Decimal(text.replace(",", ""))
                    except (DecimalException, ValueError):
                        return ("value", text)
                    return ("number", number)
                if column_type == "boolean":
                    lowered = text.casefold()
                    if lowered in {"true", "false"}:
                        return ("boolean", lowered == "true")
                return ("value", text)

            output_rows = []
            seen_values: set[tuple[tuple[str, Any], ...]] = set()
            for row in source_rows:
                key = tuple(value_key(row.get(column), column) for column in output_headers)
                if key in seen_values:
                    continue
                seen_values.add(key)
                output_rows.append({column: row.get(column, "") for column in output_headers})

        value_context = dict(source_context)
        value_context["headers"] = output_headers
        value_context["rows"] = output_rows
        return value_context, output_rows

    def table_argument_value(
        argument: tuple[Any, ...],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if argument[0] == "table":
            context = resolve_table_context(str(argument[1]))
            table_rows = rows_by_table_id[context["id"]]
            current_context = evaluation_contexts_by_id.get(
                context["id"], context
            )
            if (
                context["id"] in unknown_member_ids
                and context["id"] not in unknown_member_exclusions
                and unknown_member_passes_remaining_filters(
                    current_context,
                    evaluation_contexts_by_id,
                    evaluation_filter_ids,
                )
            ):
                table_rows = [
                    *table_rows,
                    {header: "" for header in current_context["headers"]},
                ]
            return context, table_rows
        if argument[0] == "call" and argument[1] in {
            "ALL", "ALLNOBLANKROW", "ALLSELECTED"
        }:
            return all_table_value(argument)
        raise MeasureError("This table expression is not supported in the local DAX engine.")

    def numeric_values(column: str, table: str) -> list[Decimal]:
        context, actual = resolve_table(table, column)
        values = []
        filtered_rows = rows_by_table_id[context["id"]]
        for row_index, row in enumerate(filtered_rows, 1):
            value = str(row.get(actual, "") or "").strip()
            if not value:
                continue
            try:
                number = Decimal(value.replace(",", ""))
            except (DecimalException, ValueError) as exc:
                raise MeasureError(
                    f"Column {actual!r} contains a non-numeric value at row {row_index}; convert it to a number first."
                ) from exc
            if not number.is_finite():
                raise MeasureError(f"Column {actual!r} contains a non-finite number.")
            values.append(number)
        return values

    def as_number(value: Decimal | bool | None) -> Decimal:
        if value is None:
            return Decimal(0)
        if not isinstance(value, Decimal):
            raise MeasureError("This expression needs a numeric value.")
        return value

    def as_boolean(value: Decimal | bool | None) -> bool:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, Decimal):
            return value != 0
        raise MeasureError("This expression needs a logical value.")

    def evaluate_with_date_values(
        expression: tuple[Any, ...],
        date_table: dict[str, Any],
        date_column: str,
        selected_dates: set[date],
    ) -> Decimal:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        period_rows = []
        period_indexes: set[int] = set()
        for row_index, row in enumerate(date_table["rows"]):
            parsed_date = _parse_measure_date(
                row.get(date_column), date_column, row_index + 1
            )
            if parsed_date in selected_dates:
                period_indexes.add(row_index)
                period_rows.append(row)
        time_contexts_by_id = {}
        for table_id, context in evaluation_contexts_by_id.items():
            updated = dict(context)
            if table_id == date_table["id"]:
                if "filter_table_rows" in context:
                    raise MeasureError(
                        "A time-intelligence filter cannot replace a table-valued FILTER rowset yet."
                    )
                if context.get("filter_context_complete", False):
                    column_filters = {
                        column: set(indexes)
                        for column, indexes in context.get(
                            "filter_column_rows", {}
                        ).items()
                    }
                    old_date_column = next(
                        (
                            column for column in column_filters
                            if column.casefold() == date_column.casefold()
                        ),
                        None,
                    )
                    if old_date_column is not None:
                        del column_filters[old_date_column]
                    column_filters[date_column] = period_indexes
                    updated["filter_column_rows"] = {
                        column: frozenset(indexes)
                        for column, indexes in column_filters.items()
                    }
                    blank_allowed = dict(
                        updated.get("filter_column_blank_allowed", {})
                    )
                    if old_date_column is not None:
                        blank_allowed.pop(old_date_column, None)
                    blank_allowed[date_column] = False
                    updated["filter_column_blank_allowed"] = blank_allowed
                    updated["filter_rows"] = [
                        row
                        for row_index, row in enumerate(updated["rows"])
                        if all(
                            row_index in indexes
                            for indexes in column_filters.values()
                        )
                    ]
                else:
                    updated["filter_rows"] = period_rows
                    blank_allowed = dict(
                        updated.get("filter_column_blank_allowed", {})
                    )
                    for column in list(blank_allowed):
                        if column.casefold() == date_column.casefold():
                            del blank_allowed[column]
                    blank_allowed[date_column] = False
                    updated["filter_column_blank_allowed"] = blank_allowed
            time_contexts_by_id[table_id] = updated
        try:
            time_rows_by_table_id = propagate_relationship_filters(
                list(time_contexts_by_id.values()),
                relationship_definitions,
                evaluation_filter_ids | {date_table["id"]},
            )
        except RelationshipError as exc:
            raise MeasureError(
                f"Could not apply date context: {exc}"
            ) from exc

        previous_rows = rows_by_table_id
        previous_context = current_context
        previous_contexts = evaluation_contexts_by_id
        previous_filter_ids = evaluation_filter_ids
        context_sequence += 1
        current_context = context_sequence
        evaluation_contexts_by_id = time_contexts_by_id
        evaluation_filter_ids = evaluation_filter_ids | {date_table["id"]}
        rows_by_table_id = time_rows_by_table_id
        try:
            return as_number(evaluate(expression))
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids

    def filter_constant(node: tuple[Any, ...]) -> Any:
        kind = node[0]
        if kind == "number":
            return node[1]
        if kind == "string":
            return node[1]
        if kind == "boolean":
            return node[1]
        if kind == "blank":
            return None
        if kind == "unary":
            value = filter_constant(node[2])
            return value if node[1] == "+" else -value
        if kind == "binary":
            left = filter_constant(node[2])
            right = filter_constant(node[3])
            if node[1] == "+":
                return left + right
            if node[1] == "-":
                return left - right
            if node[1] == "*":
                return left * right
            if right == 0:
                raise MeasureError("Division by zero in a CALCULATE filter literal.")
            return left / right
        raise MeasureError("CALCULATE filter comparisons need scalar literals.")

    def typed_filter_value(
        value: Any,
        column_type: str,
        column: str,
        row_index: int | None = None,
    ) -> Any:
        """Convert a row value or scalar literal using the column's saved type."""
        is_literal = row_index is None
        if (is_literal and value is None) or (
            not is_literal and (value is None or not str(value).strip())
        ):
            if column_type == "text":
                return ""
            if column_type in {"whole_number", "decimal_number"}:
                return Decimal(0)
            if column_type == "boolean":
                return False
            if column_type == "date":
                return date(1899, 12, 30)
            if column_type == "datetime":
                return datetime(1899, 12, 30)
            if column_type == "time":
                return time.min
        raw = "" if value is None else str(value).strip()
        if column_type == "text":
            if is_literal and not isinstance(value, str):
                raise MeasureError(
                    f"Text column {column!r} needs a quoted string or BLANK() filter value."
                )
            return "" if value is None else str(value)
        if column_type in {"whole_number", "decimal_number"}:
            if is_literal and not isinstance(value, Decimal):
                raise MeasureError(
                    f"Numeric column {column!r} needs a numeric CALCULATE filter value."
                )
            try:
                parsed_number = value if is_literal else Decimal(raw.replace(",", ""))
            except (DecimalException, ValueError) as exc:
                raise MeasureError(
                    f"Column {column!r} contains a non-numeric value at row {row_index}."
                ) from exc
            if not parsed_number.is_finite() or (
                column_type == "whole_number"
                and parsed_number != parsed_number.to_integral_value()
            ):
                if is_literal:
                    raise MeasureError(
                        f"Filter values for {column_type.replace('_', ' ')} column {column!r} "
                        "must match the saved column type."
                    )
                raise MeasureError(
                    f"Column {column!r} contains a value that does not match its saved type at row {row_index}."
                )
            return parsed_number
        if column_type == "boolean":
            if is_literal:
                if not isinstance(value, bool):
                    raise MeasureError(
                        f"Boolean column {column!r} needs TRUE(), FALSE(), or BLANK() as its filter value."
                    )
                return value
            lowered = raw.casefold()
            if lowered in {"true", "false"}:
                return lowered == "true"
            raise MeasureError(
                f"Column {column!r} contains a non-boolean value at row {row_index}."
            )
        if column_type == "date":
            if is_literal:
                if not isinstance(value, str):
                    raise MeasureError(
                        f"Date column {column!r} needs a quoted ISO date filter value."
                    )
                return _parse_iso_date_literal(value, "CALCULATE")
            return _parse_measure_date(raw, column, row_index or 1)
        if column_type == "datetime":
            if is_literal and not isinstance(value, str):
                raise MeasureError(
                    f"DateTime column {column!r} needs a quoted ISO date/time filter value."
                )
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                if is_literal:
                    raise MeasureError(
                        f"DateTime filter values for {column!r} must use ISO date/time syntax."
                    ) from exc
                raise MeasureError(
                    f"Column {column!r} contains an invalid date/time at row {row_index}."
                ) from exc
        if column_type == "time":
            if is_literal and not isinstance(value, str):
                raise MeasureError(
                    f"Time column {column!r} needs a quoted ISO time filter value."
                )
            try:
                return time.fromisoformat(raw)
            except ValueError as exc:
                if is_literal:
                    raise MeasureError(
                        f"Time filter values for {column!r} must use ISO time syntax."
                    ) from exc
                raise MeasureError(
                    f"Column {column!r} contains an invalid time at row {row_index}."
                ) from exc
        raise MeasureError(f"Column {column!r} has an unsupported model type.")

    def filter_comparison_matches(
        node: tuple[Any, ...],
        row: dict[str, Any],
        row_index: int,
        column: str,
        column_type: str,
    ) -> bool:
        left, right = node[2], node[3]
        if left[0] == "reference":
            actual_value = typed_filter_value(
                row.get(column), column_type, column, row_index
            )
            expected_value = typed_filter_value(
                filter_constant(right), column_type, column
            )
        else:
            expected_value = typed_filter_value(
                row.get(column), column_type, column, row_index
            )
            actual_value = typed_filter_value(
                filter_constant(left), column_type, column
            )
        operator = node[1]
        if actual_value is None or expected_value is None:
            if operator == "=":
                return actual_value is expected_value
            if operator == "<>":
                return actual_value is not expected_value
            return False
        if column_type == "text" and operator not in {"=", "<>"}:
            raise MeasureError(
                f"Text column {column!r} supports only equality filters in this CALCULATE subset."
            )
        if column_type == "boolean" and operator not in {"=", "<>"}:
            raise MeasureError(
                f"Boolean column {column!r} supports only equality filters."
            )
        try:
            if operator == "=":
                return actual_value == expected_value
            if operator == "<>":
                return actual_value != expected_value
            if operator == "<":
                return actual_value < expected_value
            if operator == "<=":
                return actual_value <= expected_value
            if operator == ">":
                return actual_value > expected_value
            return actual_value >= expected_value
        except TypeError as exc:
            raise MeasureError(
                f"CALCULATE cannot compare the values for column {column!r}."
            ) from exc

    def filter_predicate_matches(
        node: tuple[Any, ...],
        row: dict[str, Any],
        row_index: int,
        column: str,
        column_type: str,
    ) -> bool:
        kind = node[0]
        if kind == "comparison":
            return filter_comparison_matches(
                node, row, row_index, column, column_type
            )
        if kind == "logical":
            if node[1] == "&&":
                return filter_predicate_matches(
                    node[2], row, row_index, column, column_type
                ) and filter_predicate_matches(
                    node[3], row, row_index, column, column_type
                )
            return filter_predicate_matches(
                node[2], row, row_index, column, column_type
            ) or filter_predicate_matches(
                node[3], row, row_index, column, column_type
            )
        function, arguments = node[1], node[2]
        if function == "NOT":
            return not filter_predicate_matches(
                arguments[0], row, row_index, column, column_type
            )
        if function == "AND":
            return all(
                filter_predicate_matches(
                    argument, row, row_index, column, column_type
                )
                for argument in arguments
            )
        if function == "OR":
            return any(
                filter_predicate_matches(
                    argument, row, row_index, column, column_type
                )
                for argument in arguments
            )
        raise MeasureError("Unsupported Boolean CALCULATE filter expression.")

    def compile_table_filter_predicate(
        node: tuple[Any, ...],
        filter_table: dict[str, Any],
        comparisons: dict[int, tuple[str, str, Any, str]],
    ) -> None:
        if node[0] == "comparison":
            left, right = node[2], node[3]
            reference, literal = (
                (left, right) if left[0] == "reference" else (right, left)
            )
            context, actual_column = resolve_table(reference[1], reference[2])
            if context["id"] != filter_table["id"]:
                raise MeasureError(
                    "FILTER predicates can reference columns from the same loaded table only."
                )
            column_type = str(
                filter_table.get("column_types", {}).get(actual_column, "text")
            )
            literal_value = typed_filter_value(
                filter_constant(literal), column_type, actual_column
            )
            operator = node[1]
            if reference is right:
                operator = {
                    "=": "=", "<>": "<>", "<": ">", "<=": ">=",
                    ">": "<", ">=": "<=",
                }[operator]
            if column_type == "text" and operator not in {"=", "<>"}:
                raise MeasureError(
                    f"Text column {actual_column!r} supports only equality filters in this FILTER subset."
                )
            if column_type == "boolean" and operator not in {"=", "<>"}:
                raise MeasureError(
                    f"Boolean column {actual_column!r} supports only equality filters."
                )
            comparisons[id(node)] = (
                actual_column, column_type, literal_value, operator
            )
            return
        if node[0] == "logical":
            compile_table_filter_predicate(node[2], filter_table, comparisons)
            compile_table_filter_predicate(node[3], filter_table, comparisons)
            return
        function, arguments = node[1], node[2]
        for argument in arguments:
            compile_table_filter_predicate(argument, filter_table, comparisons)

    def table_filter_predicate_matches(
        node: tuple[Any, ...],
        row: dict[str, Any],
        row_index: int,
        comparisons: dict[int, tuple[str, str, Any, str]],
    ) -> bool:
        kind = node[0]
        if kind == "comparison":
            actual_column, column_type, literal_value, operator = comparisons[id(node)]
            row_value = typed_filter_value(
                row.get(actual_column), column_type, actual_column, row_index
            )
            if row_value is None or literal_value is None:
                if operator == "=":
                    return row_value is literal_value
                if operator == "<>":
                    return row_value is not literal_value
                return False
            try:
                if operator == "=":
                    return row_value == literal_value
                if operator == "<>":
                    return row_value != literal_value
                if operator == "<":
                    return row_value < literal_value
                if operator == "<=":
                    return row_value <= literal_value
                if operator == ">":
                    return row_value > literal_value
                return row_value >= literal_value
            except TypeError as exc:
                raise MeasureError(
                    f"FILTER cannot compare values for column {actual_column!r}."
                ) from exc
        if kind == "logical":
            if node[1] == "&&":
                return table_filter_predicate_matches(
                    node[2], row, row_index, comparisons
                ) and table_filter_predicate_matches(
                    node[3], row, row_index, comparisons
                )
            return table_filter_predicate_matches(
                node[2], row, row_index, comparisons
            ) or table_filter_predicate_matches(
                node[3], row, row_index, comparisons
            )
        function, arguments = node[1], node[2]
        if function == "NOT":
            return not table_filter_predicate_matches(
                arguments[0], row, row_index, comparisons
            )
        if function == "AND":
            return all(
                table_filter_predicate_matches(
                    argument, row, row_index, comparisons
                )
                for argument in arguments
            )
        if function == "OR":
            return any(
                table_filter_predicate_matches(
                    argument, row, row_index, comparisons
                )
                for argument in arguments
            )
        raise MeasureError("Unsupported FILTER row predicate.")

    def evaluate_with_boolean_filters(
        expression: tuple[Any, ...],
        filter_arguments: tuple[tuple[Any, ...], ...],
        extra_date_filters: dict[tuple[str, str], tuple[dict, str, frozenset[int]]] | None = None,
    ) -> Decimal:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        filters_by_column: dict[
            tuple[str, str], list[tuple[frozenset[int], bool, bool]]
        ] = {}
        targets_by_key: dict[
            tuple[str, str], tuple[dict[str, Any], str]
        ] = {}
        for key, (target_context, target_column, allowed_rows) in (extra_date_filters or {}).items():
            filters_by_column.setdefault(key, []).append((allowed_rows, False, False))
            targets_by_key[key] = (target_context, target_column)

        for filter_argument in filter_arguments:
            predicate, keep = _calculate_filter_argument(filter_argument)
            references = list(_iter_reference_nodes(predicate))
            if not references:
                raise MeasureError("A CALCULATE Boolean filter must reference a loaded column.")
            target_context: dict[str, Any] | None = None
            target_column = ""
            for reference in references:
                if not reference[1] and reference[2].casefold() in by_name:
                    raise MeasureError("CALCULATE Boolean filters cannot reference measures.")
                context, actual = resolve_table(reference[1], reference[2])
                if target_context is None:
                    target_context, target_column = context, actual
                elif (
                    context["id"] != target_context["id"]
                    or actual.casefold() != target_column.casefold()
                ):
                    raise MeasureError(
                        "One CALCULATE Boolean filter can reference only one loaded column."
                    )
            assert target_context is not None
            table_id = target_context["id"]
            if "filter_table_rows" in target_context:
                raise MeasureError(
                    "Boolean CALCULATE filters cannot replace a table-valued FILTER rowset yet."
                )
            if table_id in evaluation_filter_ids and not target_context.get("filter_context_complete", False):
                raise MeasureError(
                    "CALCULATE cannot replace a saved filter because its per-column "
                    "filter context is unavailable."
                )
            column_type = str(
                target_context.get("column_types", {}).get(target_column, "text")
            )
            allowed_rows = frozenset(
                row_index
                for row_index, row in enumerate(target_context["rows"])
                if filter_predicate_matches(
                    predicate, row, row_index + 1, target_column, column_type
                )
            )
            blank_allowed = filter_predicate_matches(
                predicate,
                {target_column: ""},
                len(target_context["rows"]) + 1,
                target_column,
                column_type,
            )
            key = (table_id, target_column.casefold())
            filters_by_column.setdefault(key, []).append(
                (allowed_rows, keep, blank_allowed)
            )
            targets_by_key[key] = (target_context, target_column)

        updated_contexts = [
            dict(context) for context in evaluation_contexts_by_id.values()
        ]
        updated_by_id = {context["id"]: context for context in updated_contexts}
        updated_filter_roots = set(evaluation_filter_ids)
        for key, filter_sets in filters_by_column.items():
            modes = {keep for _rows, keep, _blank_allowed in filter_sets}
            if len(modes) != 1:
                raise MeasureError(
                    "Use either replacement filters or KEEPFILTERS for a column "
                    "within one CALCULATE call."
                )
            new_rows = set(filter_sets[0][0])
            for allowed_rows, _keep, _blank_allowed in filter_sets[1:]:
                new_rows.intersection_update(allowed_rows)
            new_blank_allowed = all(
                blank_allowed
                for _allowed_rows, _keep, blank_allowed in filter_sets
            )
            target_context, actual_column = targets_by_key[key]
            table_id = target_context["id"]
            if not target_context.get("filter_context_complete", False):
                is_date_replacement = extra_date_filters is not None and key in extra_date_filters
                if table_id in evaluation_filter_ids and not is_date_replacement:
                    raise MeasureError(
                        "CALCULATE cannot replace a saved filter because its per-column "
                        "filter context is unavailable."
                    )
            updated = updated_by_id[table_id]
            column_filters = {
                column: set(indexes)
                for column, indexes in updated.get(
                    "filter_column_rows", {}
                ).items()
            }
            existing_key = next(
                (
                    column for column in column_filters
                    if column.casefold() == actual_column.casefold()
                ),
                None,
            )
            keep = next(iter(modes))
            if keep and existing_key is not None:
                new_rows.intersection_update(column_filters[existing_key])
                previous_blank_allowed = updated.get(
                    "filter_column_blank_allowed", {}
                ).get(existing_key)
                if previous_blank_allowed is not None:
                    new_blank_allowed = new_blank_allowed and previous_blank_allowed
            if existing_key is not None:
                del column_filters[existing_key]
            column_filters[actual_column] = new_rows

            blank_column_filters = dict(
                updated.get("filter_column_blank_allowed", {})
            )
            if existing_key is not None:
                blank_column_filters.pop(existing_key, None)
            if not (
                keep
                and existing_key is not None
                and existing_key not in updated.get(
                    "filter_column_blank_allowed", {}
                )
            ):
                blank_column_filters[actual_column] = new_blank_allowed

            updated["filter_context_complete"] = True
            updated["filter_column_rows"] = {
                column: frozenset(indexes)
                for column, indexes in column_filters.items()
            }
            updated["filter_column_blank_allowed"] = blank_column_filters
            updated["filter_rows"] = [
                row
                for row_index, row in enumerate(updated["rows"])
                if all(
                    row_index in indexes
                    for indexes in column_filters.values()
                )
            ]
            updated_filter_roots.add(table_id)

        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(
                f"Could not apply CALCULATE filters: {exc}"
            ) from exc

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
            return as_number(evaluate(expression))
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids

    def evaluate_with_allselected(
        expression: tuple[Any, ...],
        modifier: tuple[Any, ...],
    ) -> Decimal:
        """Evaluate in the saved selection context when no query-axis context exists."""
        arguments = modifier[2]
        if arguments and arguments[0][0] == "table":
            resolve_table_context(str(arguments[0][1]))
        elif arguments:
            resolved_columns = [
                resolve_table(reference[1], reference[2])
                for reference in arguments
            ]
            if any(
                context["id"] != resolved_columns[0][0]["id"]
                for context, _column in resolved_columns[1:]
            ):
                raise MeasureError(
                    "ALLSELECTED column arguments must resolve to one loaded table."
                )
        # The local report evaluator has saved report/page/visual selections and
        # relationship roots, but it does not create DAX query row/column filters.
        # With no such axis context to remove, ALLSELECTED keeps the current context.
        return as_number(evaluate(expression))

    def evaluate_with_userelationships(
        expression: tuple[Any, ...],
        modifiers: tuple[tuple[Any, ...], ...],
    ) -> Decimal:
        """Evaluate with saved relationship links temporarily selected."""
        nonlocal relationship_definitions, rows_by_table_id
        nonlocal context_sequence, current_context
        nonlocal unknown_member_ids

        selected: dict[int, set[tuple[tuple[str, str], tuple[str, str]]]] = {}
        table_pair_relationships: dict[tuple[str, str], int] = {}
        relationship_pairs: dict[int, tuple[str, str]] = {}
        for modifier in modifiers:
            left_context, left_column = resolve_table(
                modifier[2][0][1], modifier[2][0][2]
            )
            right_context, right_column = resolve_table(
                modifier[2][1][1], modifier[2][1][2]
            )
            if left_context["id"] == right_context["id"]:
                raise MeasureError(
                    "USERELATIONSHIP columns must belong to two different loaded tables."
                )
            left_endpoint = (left_context["id"], left_column.casefold())
            right_endpoint = (right_context["id"], right_column.casefold())
            endpoint_set = frozenset((left_endpoint, right_endpoint))
            matches = [
                index
                for index, relationship in enumerate(relationship_definitions)
                if (
                    isinstance(relationship, dict)
                    and type(relationship.get("relationship_version")) is int
                    and relationship.get("relationship_version") == 1
                    and frozenset((
                        (
                            str(relationship.get("from_table_id", "")),
                            str(relationship.get("from_column", "")).casefold(),
                        ),
                        (
                            str(relationship.get("to_table_id", "")),
                            str(relationship.get("to_column", "")).casefold(),
                        ),
                    )) == endpoint_set
                )
            ]
            if len(matches) != 1:
                raise MeasureError(
                    "USERELATIONSHIP columns must identify one existing model relationship."
                )
            relationship_index = matches[0]
            relationship = relationship_definitions[relationship_index]
            pair = tuple(sorted((left_context["id"], right_context["id"])))
            previous_index = table_pair_relationships.get(pair)
            if previous_index is not None and previous_index != relationship_index:
                raise MeasureError(
                    "One CALCULATE call cannot select competing USERELATIONSHIP links between the same two tables."
                )
            table_pair_relationships[pair] = relationship_index
            relationship_pairs[relationship_index] = pair
            selected.setdefault(relationship_index, set()).add(
                (left_endpoint, right_endpoint)
            )

        updated_relationships = [
            dict(relationship) if isinstance(relationship, dict) else relationship
            for relationship in relationship_definitions
        ]
        for relationship_index, orientations in selected.items():
            relationship = updated_relationships[relationship_index]
            pair = relationship_pairs[relationship_index]
            for index, candidate in enumerate(updated_relationships):
                if (
                    index != relationship_index
                    and isinstance(candidate, dict)
                    and tuple(sorted((
                        str(candidate.get("from_table_id", "")),
                        str(candidate.get("to_table_id", "")),
                    ))) == pair
                ):
                    candidate["is_active"] = False
            relationship["is_active"] = True
            if relationship.get("cardinality") == "one_to_one":
                if len(orientations) > 1:
                    relationship["cross_filter_direction"] = "both"
                else:
                    left_endpoint, right_endpoint = next(iter(orientations))
                    # USERELATIONSHIP's second column filters the first on a
                    # one-to-one link. Reorient the temporary single edge to
                    # match that direction; the stored model is unchanged.
                    source_endpoint, target_endpoint = right_endpoint, left_endpoint
                    current_source = (
                        str(relationship.get("from_table_id", "")),
                        str(relationship.get("from_column", "")).casefold(),
                    )
                    if current_source != source_endpoint:
                        relationship["from_table_id"], relationship["to_table_id"] = (
                            relationship.get("to_table_id"),
                            relationship.get("from_table_id"),
                        )
                        relationship["from_column"], relationship["to_column"] = (
                            relationship.get("to_column"),
                            relationship.get("from_column"),
                        )
                    relationship["cross_filter_direction"] = "single"

        previous_relationships = relationship_definitions
        previous_rows = rows_by_table_id
        previous_context = current_context
        previous_unknown_members = unknown_member_ids
        try:
            relationship_definitions = updated_relationships
            rows_by_table_id = propagate_relationship_filters(
                list(evaluation_contexts_by_id.values()),
                relationship_definitions,
                evaluation_filter_ids,
            )
            unknown_member_ids = unknown_member_table_ids(
                list(evaluation_contexts_by_id.values()),
                relationship_definitions,
                rows_by_table_id,
            )
        except (RelationshipError, DecimalException) as exc:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            unknown_member_ids = previous_unknown_members
            raise MeasureError(
                f"Could not apply USERELATIONSHIP: {exc}"
            ) from exc

        context_sequence += 1
        current_context = context_sequence
        try:
            return as_number(evaluate(expression))
        finally:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            current_context = previous_context
            unknown_member_ids = previous_unknown_members

    def evaluate_with_crossfilters(
        expression: tuple[Any, ...],
        modifiers: tuple[tuple[Any, ...], ...],
    ) -> Decimal:
        """Evaluate with temporary cross-filter directions on active links."""
        nonlocal relationship_definitions, rows_by_table_id
        nonlocal context_sequence, current_context, unknown_member_ids

        selected_directions: dict[int, str] = {}
        table_pair_relationships: dict[tuple[str, str], int] = {}
        for modifier in modifiers:
            left_context, left_column = resolve_table(
                modifier[2][0][1], modifier[2][0][2]
            )
            right_context, right_column = resolve_table(
                modifier[2][1][1], modifier[2][1][2]
            )
            if left_context["id"] == right_context["id"]:
                raise MeasureError(
                    "CROSSFILTER columns must belong to two different loaded tables."
                )
            left_endpoint = (left_context["id"], left_column.casefold())
            right_endpoint = (right_context["id"], right_column.casefold())
            endpoint_set = frozenset((left_endpoint, right_endpoint))
            matches = [
                index
                for index, relationship in enumerate(relationship_definitions)
                if (
                    isinstance(relationship, dict)
                    and type(relationship.get("relationship_version")) is int
                    and relationship.get("relationship_version") == 1
                    and frozenset((
                        (
                            str(relationship.get("from_table_id", "")),
                            str(relationship.get("from_column", "")).casefold(),
                        ),
                        (
                            str(relationship.get("to_table_id", "")),
                            str(relationship.get("to_column", "")).casefold(),
                        ),
                    )) == endpoint_set
                )
            ]
            if len(matches) != 1:
                raise MeasureError(
                    "CROSSFILTER columns must identify one existing model relationship."
                )
            relationship_index = matches[0]
            relationship = relationship_definitions[relationship_index]
            if not relationship.get("is_active"):
                raise MeasureError(
                    "CROSSFILTER needs an active relationship in this local subset."
                )
            pair = tuple(sorted((left_context["id"], right_context["id"])))
            previous_index = table_pair_relationships.get(pair)
            if previous_index is not None and previous_index != relationship_index:
                raise MeasureError(
                    "One CALCULATE call cannot target competing CROSSFILTER links between the same two tables."
                )
            table_pair_relationships[pair] = relationship_index

            direction = str(modifier[2][2][1]).upper()
            cardinality = relationship.get("cardinality")
            if direction == "BOTH":
                filter_direction = "both"
            elif direction == "NONE":
                filter_direction = "none"
            elif direction == "ONEWAY":
                if cardinality in {"one_to_one", "many_to_many"}:
                    raise MeasureError(
                        f"CROSSFILTER OneWay is ambiguous for a {cardinality.replace('_', '-')} relationship."
                    )
                filter_direction = (
                    "from_to" if cardinality == "one_to_many" else "to_from"
                )
            elif direction in {
                "ONEWAY_LEFTFILTERSRIGHT", "ONEWAY_RIGHTFILTERSLEFT"
            }:
                if cardinality in {"one_to_one", "many_to_one"}:
                    raise MeasureError(
                        f"CROSSFILTER {direction.title()} is not supported for a {cardinality.replace('_', '-')} relationship."
                    )
                if cardinality == "one_to_many":
                    # Microsoft normalizes reversed endpoint arguments so the
                    # first endpoint is the many side and the second is the
                    # lookup side for this direction pair.
                    left_to_right = direction == "ONEWAY_LEFTFILTERSRIGHT"
                    filter_direction = "to_from" if left_to_right else "from_to"
                else:
                    from_endpoint = (
                        str(relationship.get("from_table_id", "")),
                        str(relationship.get("from_column", "")).casefold(),
                    )
                    left_is_from = left_endpoint == from_endpoint
                    left_to_right = direction == "ONEWAY_LEFTFILTERSRIGHT"
                    goes_from_to = left_is_from == left_to_right
                    filter_direction = "from_to" if goes_from_to else "to_from"
            else:
                raise MeasureError("CROSSFILTER direction is not supported.")

            previous_direction = selected_directions.get(relationship_index)
            if previous_direction is not None and previous_direction != filter_direction:
                raise MeasureError(
                    "One CALCULATE call cannot assign conflicting directions to the same relationship."
                )
            selected_directions[relationship_index] = filter_direction

        updated_relationships = [
            dict(relationship) if isinstance(relationship, dict) else relationship
            for relationship in relationship_definitions
        ]
        for relationship_index, filter_direction in selected_directions.items():
            updated_relationships[relationship_index]["filter_direction_override"] = (
                filter_direction
            )

        previous_relationships = relationship_definitions
        previous_rows = rows_by_table_id
        previous_context = current_context
        previous_unknown_members = unknown_member_ids
        try:
            relationship_definitions = updated_relationships
            rows_by_table_id = propagate_relationship_filters(
                list(evaluation_contexts_by_id.values()),
                relationship_definitions,
                evaluation_filter_ids,
            )
            unknown_member_ids = unknown_member_table_ids(
                list(evaluation_contexts_by_id.values()),
                relationship_definitions,
                rows_by_table_id,
            )
        except (RelationshipError, DecimalException) as exc:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            unknown_member_ids = previous_unknown_members
            raise MeasureError(f"Could not apply CROSSFILTER: {exc}") from exc

        context_sequence += 1
        current_context = context_sequence
        try:
            return as_number(evaluate(expression))
        finally:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            current_context = previous_context
            unknown_member_ids = previous_unknown_members

    def evaluate_with_filter_clear(
        expression: tuple[Any, ...],
        modifier: tuple[Any, ...],
        function: str,
    ) -> Decimal:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        nonlocal unknown_member_exclusions
        modifier_arguments = modifier[2]
        clear_all = not modifier_arguments
        target_context: dict[str, Any] | None = None
        columns_to_clear: set[str] = set()
        if function == "ALLEXCEPT":
            target_context = resolve_table_context(str(modifier_arguments[0][1]))
            preserved_columns: set[str] = set()
            for reference in modifier_arguments[1:]:
                context, actual_column = resolve_table(
                    reference[1], reference[2]
                )
                if context["id"] != target_context["id"]:
                    raise MeasureError(
                        "ALLEXCEPT columns must resolve to its first table."
                    )
                preserved_columns.add(actual_column.casefold())
            columns_to_clear = {
                column.casefold()
                for column in target_context["headers"]
                if column.casefold() not in preserved_columns
            }
        elif modifier_arguments and modifier_arguments[0][0] == "table":
            target_context = resolve_table_context(str(modifier_arguments[0][1]))
        elif modifier_arguments:
            for reference in modifier_arguments:
                context, actual_column = resolve_table(
                    reference[1], reference[2]
                )
                if target_context is None:
                    target_context = context
                elif context["id"] != target_context["id"]:
                    raise MeasureError(
                        f"{function} column arguments must resolve to one loaded table."
                    )
                columns_to_clear.add(actual_column.casefold())

        updated_contexts = [
            dict(context) for context in evaluation_contexts_by_id.values()
        ]
        updated_by_id = {context["id"]: context for context in updated_contexts}
        updated_filter_roots = set(evaluation_filter_ids)
        if clear_all:
            updated_filter_roots.clear()
            targets = list(updated_by_id.values())
        else:
            assert target_context is not None
            targets = [updated_by_id[target_context["id"]]]

        for updated in targets:
            if function == "ALLEXCEPT" and not columns_to_clear:
                continue
            if clear_all or (
                updated["id"] == target_context["id"] and not columns_to_clear
            ):
                updated.pop("filter_rows", None)
                updated.pop("filter_table_rows", None)
                updated["filter_column_rows"] = {}
                updated["filter_column_blank_allowed"] = {}
                updated["filter_context_complete"] = True
                updated_filter_roots.discard(updated["id"])
                continue

            if "filter_table_rows" in updated:
                raise MeasureError(
                    f"{function} cannot clear individual columns from an opaque table-valued FILTER rowset."
                )
            existing_column_rows = updated.get("filter_column_rows", {})
            has_direct_filter_state = (
                updated["id"] in updated_filter_roots
                or "filter_rows" in updated
                or bool(existing_column_rows)
            )
            if (
                has_direct_filter_state
                and not updated.get("filter_context_complete", False)
            ):
                raise MeasureError(
                    f"{function} cannot clear individual columns because their per-column filter context is unavailable."
                )
            remaining_column_rows = {
                column: frozenset(indexes)
                for column, indexes in existing_column_rows.items()
                if column.casefold() not in columns_to_clear
            }
            updated["filter_column_rows"] = remaining_column_rows
            updated["filter_column_blank_allowed"] = {
                column: allowed
                for column, allowed in updated.get(
                    "filter_column_blank_allowed", {}
                ).items()
                if column.casefold() not in columns_to_clear
            }
            updated["filter_context_complete"] = True
            if remaining_column_rows:
                updated["filter_rows"] = [
                    row
                    for row_index, row in enumerate(updated["rows"])
                    if all(
                        row_index in indexes
                        for indexes in remaining_column_rows.values()
                    )
                ]
            else:
                updated.pop("filter_rows", None)
                updated_filter_roots.discard(updated["id"])

        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(
                f"Could not apply {function}: {exc}"
            ) from exc

        previous_rows = rows_by_table_id
        previous_context = current_context
        previous_contexts = evaluation_contexts_by_id
        previous_filter_ids = evaluation_filter_ids
        previous_unknown_member_exclusions = unknown_member_exclusions
        updated_unknown_member_exclusions = {
            table_id: None if columns is None else set(columns)
            for table_id, columns in unknown_member_exclusions.items()
        }
        if clear_all:
            updated_unknown_member_exclusions.clear()
        elif target_context is not None:
            target_id = target_context["id"]
            if function == "ALLNOBLANKROW":
                if columns_to_clear:
                    existing_exclusions = updated_unknown_member_exclusions.get(
                        target_id, set()
                    )
                    if existing_exclusions is not None:
                        updated_unknown_member_exclusions[target_id] = (
                            existing_exclusions | columns_to_clear
                        )
                else:
                    updated_unknown_member_exclusions[target_id] = None
            elif function == "ALLEXCEPT" and columns_to_clear:
                existing_exclusions = updated_unknown_member_exclusions.get(target_id)
                if existing_exclusions is None:
                    updated_unknown_member_exclusions.pop(target_id, None)
                else:
                    remaining_exclusions = existing_exclusions - columns_to_clear
                    if remaining_exclusions:
                        updated_unknown_member_exclusions[target_id] = remaining_exclusions
                    else:
                        updated_unknown_member_exclusions.pop(target_id, None)
            elif not columns_to_clear:
                updated_unknown_member_exclusions.pop(target_id, None)
            elif target_id in updated_unknown_member_exclusions:
                existing_exclusions = updated_unknown_member_exclusions[target_id]
                if existing_exclusions is not None:
                    remaining_exclusions = existing_exclusions - columns_to_clear
                    if remaining_exclusions:
                        updated_unknown_member_exclusions[target_id] = remaining_exclusions
                    else:
                        updated_unknown_member_exclusions.pop(target_id, None)
        unknown_member_exclusions = updated_unknown_member_exclusions
        context_sequence += 1
        current_context = context_sequence
        evaluation_contexts_by_id = updated_by_id
        evaluation_filter_ids = updated_filter_roots
        rows_by_table_id = filtered_rows_by_id
        try:
            return as_number(evaluate(expression))
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids
            unknown_member_exclusions = previous_unknown_member_exclusions

    def evaluate_with_table_filter(
        expression: tuple[Any, ...],
        filter_node: tuple[Any, ...],
    ) -> Decimal:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        table_name = str(filter_node[2][0][1])
        predicate = filter_node[2][1]
        target_context = resolve_table_context(table_name)
        table_id = target_context["id"]
        if "filter_table_rows" in target_context:
            raise MeasureError(
                "Nested table-valued FILTER replacement on the same table is not supported yet."
            )
        comparisons: dict[int, tuple[str, str, Any, str]] = {}
        compile_table_filter_predicate(predicate, target_context, comparisons)

        # Relationship propagation preserves row objects, so identity maps
        # the visible rows back to original row positions without collapsing
        # duplicate-valued rows.
        visible_counts = Counter(
            id(row) for row in rows_by_table_id.get(table_id, [])
        )
        matching_indexes: set[int] = set()
        for row_index, row in enumerate(target_context["rows"]):
            row_identity = id(row)
            visible_count = visible_counts.get(row_identity, 0)
            if visible_count <= 0:
                continue
            visible_counts[row_identity] = visible_count - 1
            if table_filter_predicate_matches(
                predicate, row, row_index + 1, comparisons
            ):
                matching_indexes.add(row_index)

        updated_contexts = [
            dict(context) for context in evaluation_contexts_by_id.values()
        ]
        updated_by_id = {context["id"]: context for context in updated_contexts}
        updated = updated_by_id[table_id]
        updated["filter_rows"] = [
            row
            for row_index, row in enumerate(updated["rows"])
            if row_index in matching_indexes
        ]
        updated["filter_table_rows"] = frozenset(matching_indexes)
        updated["filter_column_rows"] = {}
        updated["filter_context_complete"] = False
        updated_filter_roots = set(evaluation_filter_ids)
        updated_filter_roots.add(table_id)

        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(
                f"Could not apply CALCULATE table filter: {exc}"
            ) from exc

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
            return as_number(evaluate(expression))
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids


    def evaluate_with_context_transition(
        expression_node: tuple[Any, ...],
        iterated_table: dict[str, Any],
        row: dict[str, Any],
    ) -> Decimal | bool | None:
        '''Create a filter context mimicking the current row context and evaluate.'''
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids

        table_id = iterated_table["id"]
        allowed_rows = frozenset(
            row_index
            for row_index, iterate_row in enumerate(iterated_table["rows"])
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
        target_context["filter_rows"] = [
            row for row_index, row in enumerate(target_context["rows"])
            if all(row_index in indexes for indexes in updated_column_rows.values())
        ]
        
        updated_filter_roots = evaluation_filter_ids | {table_id}
        
        updated_contexts = list(updated_by_id.values())
        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(str(exc)) from exc

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
            return evaluate(expression_node)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids

    def evaluate(
        node: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None = None,
    ) -> Decimal | bool | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        kind = node[0]
        if kind == "number":
            return node[1]
        if kind == "boolean":
            return node[1]
        if kind == "table":
            raise MeasureError("A table name is only supported as the first argument to SUMX or AVERAGEX.")
        if kind == "reference":
            _, table, name = node
            measure_key = name.casefold()
            if measure_key in by_name:
                if row_context is not None:
                    return evaluate_with_context_transition(node, row_context[0], row_context[1])
                return resolve(measure_key)
            if row_context is not None:
                iterated_table, row, row_index = row_context
                value_table = resolve_table_context(table) if table else iterated_table
                if value_table["id"] != iterated_table["id"]:
                    raise MeasureError(
                        "SUMX/AVERAGEX expressions can reference columns from their iterated table only."
                    )
                header_by_key = {
                    header.casefold(): header for header in iterated_table["headers"]
                }
                actual = header_by_key.get(name.casefold())
                if actual is None:
                    raise MeasureError(
                        f"Column {name!r} does not exist in table {iterated_table['name']!r}."
                    )
                raw_value = str(row.get(actual, "") or "").strip()
                if not raw_value:
                    return None
                if str(iterated_table.get("column_types", {}).get(actual, "text")) == "boolean":
                    lowered = raw_value.casefold()
                    if lowered in {"true", "false"}:
                        return lowered == "true"
                    raise MeasureError(
                        f"Column {actual!r} contains a value that is not True or False at row {row_index}."
                    )
                try:
                    number = Decimal(raw_value.replace(",", ""))
                except (DecimalException, ValueError) as exc:
                    raise MeasureError(
                        f"Column {actual!r} contains a non-numeric value at row {row_index}; convert it to a number first."
                    ) from exc
                if not number.is_finite():
                    raise MeasureError(f"Column {actual!r} contains a non-finite number.")
                return number
            raise MeasureError(f"{name!r} is a column reference; use an aggregation such as SUM([{name}]).")
        if kind == "unary":
            value = as_number(evaluate(node[2], row_context))
            return value if node[1] == "+" else -value
        if kind == "binary":
            left = as_number(evaluate(node[2], row_context))
            right = as_number(evaluate(node[3], row_context))
            if node[1] == "+": return left + right
            if node[1] == "-": return left - right
            if node[1] == "*": return left * right
            if right == 0: raise MeasureError("Division by zero; use DIVIDE() to choose an alternate result.")
            return left / right
        if kind == "logical":
            left = as_boolean(evaluate(node[2], row_context))
            if node[1] == "&&":
                return left and as_boolean(evaluate(node[3], row_context))
            return left or as_boolean(evaluate(node[3], row_context))
        if kind == "comparison":
            left = evaluate(node[2], row_context)
            right = evaluate(node[3], row_context)
            if isinstance(left, bool) and isinstance(right, bool):
                if node[1] == "=": return left == right
                if node[1] == "<>": return left != right
                raise MeasureError("True/False values support only equality comparisons.")
            left_number, right_number = as_number(left), as_number(right)
            if node[1] == "=": return left_number == right_number
            if node[1] == "<>": return left_number != right_number
            if node[1] == "<": return left_number < right_number
            if node[1] == "<=": return left_number <= right_number
            if node[1] == ">": return left_number > right_number
            return left_number >= right_number
        _, function, arguments = node
        if function in {"SUMX", "AVERAGEX"}:
            context, iteration_rows = table_argument_value(arguments[0])
            values: list[Decimal] = []
            for row_index, row in enumerate(iteration_rows, 1):
                result = evaluate(arguments[1], (context, row, row_index))
                if result is not None:
                    values.append(as_number(result))
            if not values:
                return Decimal(0)
            total = sum(values, Decimal(0))
            return total if function == "SUMX" else total / Decimal(len(values))
        if function == "CALCULATE":
            if row_context is not None:
                return evaluate_with_context_transition(node, row_context[0], row_context[1])
            if len(arguments) == 1:
                return as_number(evaluate(arguments[0]))
            if arguments[1:] and all(
                argument[0] == "call" and argument[1] == "USERELATIONSHIP"
                for argument in arguments[1:]
            ):
                return evaluate_with_userelationships(
                    arguments[0], tuple(arguments[1:])
                )
            if arguments[1:] and all(
                argument[0] == "call" and argument[1] == "CROSSFILTER"
                for argument in arguments[1:]
            ):
                return evaluate_with_crossfilters(
                    arguments[0], tuple(arguments[1:])
                )
            if (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1]
                in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT"}
            ):
                return evaluate_with_filter_clear(
                    arguments[0], arguments[1], arguments[1][1]
                )
            if (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1] == "ALLSELECTED"
            ):
                return evaluate_with_allselected(arguments[0], arguments[1])
            if (
                len(arguments) == 2
                and arguments[1][0] == "call"
                and arguments[1][1] == "FILTER"
            ):
                return evaluate_with_table_filter(arguments[0], arguments[1])
            time_filters = [
                arg for arg in arguments[1:]
                if arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS
            ]
            boolean_filters = tuple(
                arg for arg in arguments[1:]
                if not (arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS)
            )
            if not time_filters:
                return evaluate_with_boolean_filters(
                    arguments[0], boolean_filters
                )

            extra_date_filters = {}
            for date_filter in time_filters:
                date_filter_function = date_filter[1]
                date_filter_arguments = date_filter[2]
                date_reference = date_filter_arguments[0]
                date_table, actual_date_column = resolve_table(
                    date_reference[1], date_reference[2]
                )
                if (
                    date_table["date_column"].casefold() != actual_date_column.casefold()
                    or str(date_table["column_types"].get(actual_date_column, ""))
                    not in {"date", "datetime"}
                ):
                    raise MeasureError(
                        f"{date_filter_function} needs the marked Date or DateTime column of a date table."
                    )
                visible_dates = [
                    parsed_date
                    for row_index, row in enumerate(
                        rows_by_table_id[date_table["id"]], 1
                    )
                    if (parsed_date := _parse_measure_date(
                        row.get(actual_date_column), actual_date_column, row_index
                    )) is not None
                ]
                if date_filter_function == "DATEADD":
                    interval_value = as_number(evaluate(date_filter_arguments[1]))
                    if interval_value != interval_value.to_integral_value():
                        raise MeasureError("DATEADD number_of_intervals must be a whole number.")
                    if abs(interval_value) > Decimal(3_652_059):
                        raise MeasureError("DATEADD number_of_intervals is outside the supported range.")
                    shifted_dates = _dateadd_dates(
                        visible_dates,
                        int(interval_value),
                        str(date_filter_arguments[2][1]),
                    )
                elif date_filter_function == "SAMEPERIODLASTYEAR":
                    shifted_dates = _sameperiodlastyear_dates(visible_dates)
                elif date_filter_function == "PREVIOUSYEAR":
                    year_end = (
                        _parse_year_end_date(date_filter_arguments[1][1])
                        if len(date_filter_arguments) == 2
                        else (12, 31)
                    )
                    available_dates = [
                        parsed_date
                        for row_index, row in enumerate(date_table["rows"], 1)
                        if (parsed_date := _parse_measure_date(
                            row.get(actual_date_column), actual_date_column, row_index
                        )) is not None
                    ]
                    shifted_dates = _previousyear_dates(
                        visible_dates, available_dates, year_end
                    )
                elif date_filter_function == "PREVIOUSQUARTER":
                    available_dates = [
                        parsed_date
                        for row_index, row in enumerate(date_table["rows"], 1)
                        if (parsed_date := _parse_measure_date(
                            row.get(actual_date_column), actual_date_column, row_index
                        )) is not None
                    ]
                    shifted_dates = _previousquarter_dates(
                        visible_dates, available_dates
                    )
                elif date_filter_function == "PREVIOUSMONTH":
                    available_dates = [
                        parsed_date
                        for row_index, row in enumerate(date_table["rows"], 1)
                        if (parsed_date := _parse_measure_date(
                            row.get(actual_date_column), actual_date_column, row_index
                        )) is not None
                    ]
                    shifted_dates = _previousmonth_dates(
                        visible_dates, available_dates
                    )
                elif date_filter_function == "DATESQTD":
                    shifted_dates = set()
                    if visible_dates:
                        end_date = max(visible_dates)
                        quarter_start_month = ((end_date.month - 1) // 3) * 3 + 1
                        start_date = date(end_date.year, quarter_start_month, 1)
                        shifted_dates = {
                            parsed_date
                            for row_index, row in enumerate(date_table["rows"], 1)
                            if (parsed_date := _parse_measure_date(
                                row.get(actual_date_column), actual_date_column, row_index
                            )) is not None and start_date <= parsed_date <= end_date
                        }
                elif date_filter_function == "DATESMTD":
                    shifted_dates = set()
                    if visible_dates:
                        end_date = max(visible_dates)
                        start_date = date(end_date.year, end_date.month, 1)
                        shifted_dates = {
                            parsed_date
                            for row_index, row in enumerate(date_table["rows"], 1)
                            if (parsed_date := _parse_measure_date(
                                row.get(actual_date_column), actual_date_column, row_index
                            )) is not None and start_date <= parsed_date <= end_date
                        }
                elif date_filter_function == "DATESBETWEEN":
                    available_dates = [
                        parsed_date
                        for row_index, row in enumerate(date_table["rows"], 1)
                        if (parsed_date := _parse_measure_date(
                            row.get(actual_date_column), actual_date_column, row_index
                        )) is not None
                    ]
                    shifted_dates = set()
                    if available_dates:
                        start_bound, end_bound = date_filter_arguments[1:]
                        start_date = (
                            min(available_dates)
                            if start_bound[0] == "blank"
                            else _parse_iso_date_literal(start_bound[1], "DATESBETWEEN")
                        )
                        end_date = (
                            max(available_dates)
                            if end_bound[0] == "blank"
                            else _parse_iso_date_literal(end_bound[1], "DATESBETWEEN")
                        )
                        if start_date <= end_date:
                            shifted_dates = {
                                value for value in available_dates
                                if start_date <= value <= end_date
                            }
                elif date_filter_function == "DATESINPERIOD":
                    start_date = _parse_iso_date_literal(
                        date_filter_arguments[1][1], "DATESINPERIOD"
                    )
                    interval_value = as_number(evaluate(date_filter_arguments[2]))
                    if interval_value != interval_value.to_integral_value():
                        raise MeasureError(
                            "DATESINPERIOD number_of_intervals must be a whole number."
                        )
                    if abs(interval_value) > Decimal(3_652_059):
                        raise MeasureError(
                            "DATESINPERIOD number_of_intervals is outside the supported range."
                        )
                    interval = str(date_filter_arguments[3][1])
                    shifted_boundary = next(iter(_dateadd_dates(
                        [start_date], int(interval_value), interval
                    )))
                    available_dates = [
                        parsed_date
                        for row_index, row in enumerate(date_table["rows"], 1)
                        if (parsed_date := _parse_measure_date(
                            row.get(actual_date_column), actual_date_column, row_index
                        )) is not None
                    ]
                    if interval_value < 0:
                        shifted_dates = {
                            value for value in available_dates
                            if shifted_boundary < value <= start_date
                        }
                    else:
                        shifted_dates = {
                            value for value in available_dates
                            if start_date <= value < shifted_boundary
                        }
                else:
                    shifted_dates = set()
                if date_filter_function == "DATESYTD":
                    if visible_dates:
                        date_argument = (
                            _parse_year_end_date(date_filter_arguments[1][1])
                            if len(date_filter_arguments) == 2
                            else (12, 31)
                        )
                        end_date = max(visible_dates)
                        start_date = _year_to_date_start(end_date, date_argument)
                        shifted_dates = {
                            parsed_date
                            for row_index, row in enumerate(
                                date_table["rows"], 1
                            )
                            if (parsed_date := _parse_measure_date(
                                row.get(actual_date_column), actual_date_column, row_index
                            )) is not None and start_date <= parsed_date <= end_date
                        }
                    else:
                        shifted_dates = set()
                period_indexes = frozenset(
                    row_index
                    for row_index, row in enumerate(date_table["rows"])
                    if (parsed_date := _parse_measure_date(
                        row.get(actual_date_column), actual_date_column, row_index + 1
                    )) is not None and parsed_date in shifted_dates
                )
                key = (date_table["id"], actual_date_column.casefold())
                extra_date_filters[key] = (date_table, actual_date_column, period_indexes)

            return evaluate_with_boolean_filters(
                arguments[0], boolean_filters, extra_date_filters
            )
        if function == "DATEADD":
            raise MeasureError(
                "DATEADD returns a date table; use it as a DATEADD filter in CALCULATE."
            )
        if function == "SAMEPERIODLASTYEAR":
            raise MeasureError(
                "SAMEPERIODLASTYEAR returns a date table; use it as a filter in CALCULATE."
            )
        if function == "PREVIOUSYEAR":
            raise MeasureError(
                "PREVIOUSYEAR returns a date table; use it as a filter in CALCULATE."
            )
        if function == "PREVIOUSQUARTER":
            raise MeasureError(
                "PREVIOUSQUARTER returns a date table; use it as a filter in CALCULATE."
            )
        if function == "PREVIOUSMONTH":
            raise MeasureError(
                "PREVIOUSMONTH returns a date table; use it as a filter in CALCULATE."
            )
        if function == "DATESYTD":
            raise MeasureError("DATESYTD returns a date table; use it as a filter in CALCULATE.")
        if function == "DATESQTD":
            raise MeasureError("DATESQTD returns a date table; use it as a filter in CALCULATE.")
        if function == "DATESMTD":
            raise MeasureError("DATESMTD returns a date table; use it as a filter in CALCULATE.")
        if function == "DATESBETWEEN":
            raise MeasureError(
                "DATESBETWEEN returns a date table; use it as a filter in CALCULATE."
            )
        if function == "DATESINPERIOD":
            raise MeasureError(
                "DATESINPERIOD returns a date table; use it as a filter in CALCULATE."
            )
        if function in {"TOTALYTD", "TOTALQTD", "TOTALMTD"}:
            if row_context is not None:
                raise MeasureError(f"{function} inside SUMX/AVERAGEX is not supported.")
            date_reference = arguments[1]
            date_table, actual_date_column = resolve_table(
                date_reference[1], date_reference[2]
            )
            if (
                date_table["date_column"].casefold() != actual_date_column.casefold()
                or str(date_table["column_types"].get(actual_date_column, ""))
                not in {"date", "datetime"}
            ):
                raise MeasureError(
                    f"{function} needs the marked Date or DateTime column of a date table."
                )

            visible_dates = [
                parsed
                for row_index, row in enumerate(
                    rows_by_table_id[date_table["id"]], 1
                )
                if (parsed := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            if not visible_dates:
                return Decimal(0)
            end_date = max(visible_dates)
            if function == "TOTALQTD":
                quarter_start_month = ((end_date.month - 1) // 3) * 3 + 1
                start_date = date(end_date.year, quarter_start_month, 1)
            elif function == "TOTALMTD":
                start_date = date(end_date.year, end_date.month, 1)
            else:
                year_end = (
                    _parse_year_end_date(arguments[3][1])
                    if len(arguments) == 4
                    else (12, 31)
                )
                start_date = _year_to_date_start(end_date, year_end)

            # The new period replaces the current date-table filter.
            period_dates = {
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None and start_date <= parsed_date <= end_date
            }
            return evaluate_with_date_values(
                arguments[0], date_table, actual_date_column, period_dates
            )
        if function == "IF":
            return (
                evaluate(arguments[1], row_context)
                if as_boolean(evaluate(arguments[0], row_context))
                else evaluate(arguments[2], row_context)
            )
        if function in {"AND", "OR"}:
            left = as_boolean(evaluate(arguments[0], row_context))
            if function == "AND":
                return left and as_boolean(evaluate(arguments[1], row_context))
            return left or as_boolean(evaluate(arguments[1], row_context))
        if function == "NOT":
            return not as_boolean(evaluate(arguments[0], row_context))
        if function == "COUNTROWS":
            if not arguments:
                return Decimal(len(rows_by_table_id[active_context["id"]]))
            _context, table_rows = table_argument_value(arguments[0])
            return Decimal(len(table_rows))
        if function == "DIVIDE":
            numerator = as_number(evaluate(arguments[0], row_context))
            denominator = as_number(evaluate(arguments[1], row_context))
            if denominator == 0:
                return as_number(evaluate(arguments[2], row_context)) if len(arguments) == 3 else Decimal(0)
            return numerator / denominator
        if function == "ABS":
            return abs(as_number(evaluate(arguments[0], row_context)))
        if function == "ROUND":
            value = as_number(evaluate(arguments[0], row_context))
            precision = as_number(evaluate(arguments[1], row_context))
            if precision != precision.to_integral_value() or abs(precision) > 28:
                raise MeasureError("ROUND digits must be a whole number from -28 to 28.")
            quantum = Decimal(1).scaleb(-int(precision))
            return value.quantize(quantum, rounding=ROUND_HALF_UP)
        reference = arguments[0]
        if function == "COUNTA":
            context, actual = resolve_table(reference[1], reference[2])
            return Decimal(sum(
                bool(str(row.get(actual, "") or "").strip())
                for row in rows_by_table_id[context["id"]]
            ))
        if function == "DISTINCTCOUNT":
            context, actual = resolve_table(reference[1], reference[2])
            return Decimal(len({
                str(row.get(actual, "") or "")
                for row in rows_by_table_id[context["id"]]
                if str(row.get(actual, "") or "").strip()
            }))
        values = numeric_values(reference[2], reference[1])
        if function == "COUNT": return Decimal(len(values))
        if not values:
            return Decimal(0)
        if function == "SUM": return sum(values, Decimal(0))
        if function == "AVERAGE": return sum(values, Decimal(0)) / Decimal(len(values))
        if function == "MIN": return min(values)
        return max(values)

    def resolve(key: str) -> Decimal:
        cache_key = (key, current_context)
        if cache_key in value_cache:
            return value_cache[cache_key]
        if key in resolving:
            raise MeasureError(f"Measure dependency cycle includes {by_name[key]['name']!r}.")
        resolving.add(key)
        try:
            value = as_number(evaluate(parsed[key]))
        except (DecimalException, OverflowError) as exc:
            raise MeasureError(f"Measure {by_name[key]['name']!r} is outside the supported numeric range.") from exc
        finally:
            resolving.remove(key)
        if not value.is_finite():
            raise MeasureError(f"Measure {by_name[key]['name']!r} did not produce a finite number.")
        value_cache[cache_key] = value
        return value

    targets = None if measure_names is None else {name.casefold() for name in measure_names}
    selected = [item for item in definitions if targets is None or item["name"].casefold() in targets]
    missing = targets - set(by_name) if targets is not None else set()
    if missing:
        raise MeasureError(f"Measure {sorted(missing)[0]!r} does not exist.")
    return {item["name"]: resolve(item["name"].casefold()) for item in selected}
