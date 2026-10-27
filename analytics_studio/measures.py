"""A deliberately small, safe DAX evaluator for local model calculations.

Supported expressions use scalar arithmetic, aggregate functions, and the
numeric functions ABS and ROUND. Measures also support conditionals and the
SUMX/AVERAGEX/MAXX/MINX/COUNTX/COUNTAX iterators. Calculated columns use a bounded row-scoped subset of
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
COUNTROWS, SUMX, AVERAGEX, MAXX, MINX, COUNTX, and COUNTAX, including one virtual blank parent row for
unmatched relationship keys. ALLNOBLANKROW table values omit that virtual row
while retaining physical blank rows and values.
ALLSELECTED table values retain the currently visible rows or distinct column
tuples. Its modifier form preserves the saved selection context. Visual query
row/column filters are not generally modeled; a bounded report-chart path
supplies one same-table categorical axis to qualified-column ALLSELECTED.
USERELATIONSHIP accepts saved relationship endpoint columns as direct
CALCULATE modifiers alongside supported Boolean and time-intelligence filters.
Selected links are temporary; nested calculations restore the prior context.
CROSSFILTER temporarily changes the direction of active saved links in
CALCULATE, including disabling the link, alongside those same bounded filters.
The module parses into a tiny AST and never evaluates user text as Python.
"""

from __future__ import annotations

from calendar import monthrange
import math
import getpass
from collections import Counter
from dataclasses import dataclass
from decimal import (
    Decimal, DecimalException, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP,
    localcontext,
)
from datetime import date, datetime, time, timedelta
import os
import re
from typing import Any, Callable, Iterable

from analytics_studio.relationships import (
    RelationshipError,
    _relationship_value_key,
    propagate_relationship_filters as _propagate_relationship_filters,
    relationship_filter_directions,
    unknown_member_table_ids,
)
from analytics_studio import dax_ct_filters, dax_dates, dax_ext, dax_format, dax_iteration_order, dax_math, dax_order, dax_time_sets, dax_typed
from analytics_studio.power_query_values import ascii_fold, cell_key, cell_to_text, is_cell_error


def _frozen(indexes: Iterable[int]) -> frozenset[int]:
    """frozenset(x) keeps x itself when it already is one (filters are compared by identity and a BlankSet keeps its flag)."""
    return indexes if isinstance(indexes, frozenset) else frozenset(indexes)


class BlankSet(frozenset):
    """Allowed row indexes of one column that also select the virtual blank member (a row of BLANKs) when blank is true."""

    blank: bool = False
    peer: bool = False  # the blank member was reached as the partner of an orphan row of a one-to-one table (it keeps no many-side orphans)
    many: bool = False  # the blank member was reached from a many-side row with an unknown key (it keeps no one-to-one partner orphans)

    def __new__(cls, rows: Iterable[int] = (), blank: bool = False, peer: bool = False, many: bool = False) -> "BlankSet":
        instance = super().__new__(cls, rows)
        instance.blank = blank
        instance.peer = peer
        instance.many = many
        return instance


class MeasureError(ValueError):
    """A measure definition is invalid or cannot be evaluated for this table."""


class _TableValue(tuple):
    """(context, rows) of a table stored in a VAR."""


class MeasureRuntimeError(MeasureError):
    """A data-dependent evaluation error that Power BI's IFERROR would catch."""


class _DivisionError(MeasureRuntimeError):
    """x/0 or x/BLANK(): Infinity or NaN in Power BI, an error for IFERROR."""


class _CalculateTableFilterRefusal(MeasureError):
    """A CALCULATETABLE in a Boolean filter whose hoist-or-transition reading was not established (see dax_ct_filters)."""


class _HardError(MeasureError):
    """An error Power BI throws instead of returning: IFERROR and ISERROR cannot catch it.

    Raised for an error inside a row expression (SUMX, FILTER, TOPN, IN, ...) or from a VAR that is used.
    """


_PLAN_CONSTANT_CALLS = frozenset({
    "BLANK", "TRUE", "FALSE", "PI", "SQRT", "VALUE", "LEN", "ABS", "DATE", "ISBLANK", "ISNUMBER", "ISTEXT", "ISLOGICAL",
    "ISNONTEXT", "DIVIDE", "NOT", "AND", "OR", "IF", "ROUND", "INT", "LN", "EXP", "POWER", "UPPER", "LOWER", "LEFT", "RIGHT",
    "MID", "CONCATENATE", "DATEVALUE", "MAX", "MIN", "TIME", "YEAR", "MONTH", "DAY", "SIGN", "MOD", "FIXED", "TRIM",
})


def _eager_logical(
    is_and: bool, thunks: list[Callable[[], bool]], nodes: list[tuple[Any, ...]], is_constant: Callable[[tuple[Any, ...]], bool],
    left_closed: bool = False,
) -> bool:
    """&&, ||, AND and OR as Power BI 2.157 runs them: both operands are evaluated and an error in either one is an error.

    The one way out is a plan-time constant holding the deciding value (FALSE for AND, TRUE for OR): it settles the result
    and swallows the other operand's error (tools/parity/dax_battery_evaluation_order.json).
    """
    outcomes: list[tuple[bool | None, MeasureError | None]] = []
    deciding = not is_and
    for thunk in thunks:
        try:
            outcomes.append((thunk(), None))
        except (MeasureRuntimeError, _HardError) as error:
            outcomes.append((None, error))
        if left_closed and len(outcomes) == 1 and outcomes[0][1] is None and outcomes[0][0] is deciding:
            return deciding  # an operand that does not read the row is settled first; when it decides the right side is never planned
    if any(error is not None for _value, error in outcomes):
        for (value, error), node in zip(outcomes, nodes):
            if error is None and value is deciding and is_constant(node):
                return deciding
        raise next(error for _value, error in outcomes if error is not None)
    values = [value for value, _error in outcomes]
    return all(values) if is_and else any(values)


_NOTHING = object()


class _Shadow:
    """An iterator's filter as ALLSELECTED sees it: the distinct value tuples of the iterated table over the columns it
    came from. Built lazily, because most iterations never meet an ALLSELECTED."""

    __slots__ = ("table", "columns", "_build", "_tuples")

    def __init__(self, table: str, columns: tuple[str, ...], build: Callable[[], frozenset[tuple[Any, ...]]]) -> None:
        self.table, self.columns, self._build, self._tuples = table, columns, build, None

    @property
    def tuples(self) -> frozenset[tuple[Any, ...]]:
        if self._tuples is None:
            self._tuples = self._build()
        return self._tuples

    def projected(self, dropped: frozenset[str]) -> "_Shadow | None":
        """The shadow with some columns removed (None when none are left); `dropped` holds casefolded names."""
        keep = [index for index, column in enumerate(self.columns) if column.casefold() not in dropped]
        if len(keep) == len(self.columns):
            return self
        if not keep:
            return None
        parent = self
        return _Shadow(
            self.table, tuple(self.columns[index] for index in keep),
            lambda: frozenset(tuple(item[index] for index in keep) for item in parent.tuples),
        )


_NEVER_CONSTANT_CALLS = frozenset({
    "RAND", "RANDBETWEEN", "EVALUATEANDLOG", "CALCULATE", "CALCULATETABLE", "FILTER", "ADDCOLUMNS", "SELECTCOLUMNS", "SUMMARIZE",
    "SUMMARIZECOLUMNS", "TOPN", "VALUES", "DISTINCT", "ALL", "ALLSELECTED", "ALLEXCEPT", "LOOKUPVALUE", "CONTAINS", "CONTAINSROW",
    "FIRSTNONBLANK", "LASTNONBLANK", "ISEMPTY", "RELATED", "RELATEDTABLE", "USERELATIONSHIP", "ROW", "GENERATESERIES", "ERROR",
})
_ROW_SHIELDING_CALLS = frozenset({
    "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTBLANK", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "MEDIAN", "PRODUCT",
    "VALUES", "DISTINCT", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "REMOVEFILTERS", "ISFILTERED", "ISCROSSFILTERED",
    "ISINSCOPE", "HASONEVALUE", "SELECTEDVALUE", "KEEPFILTERS", "STDEV.S", "STDEV.P", "VAR.S", "VAR.P", "NAMEOF", "TABLEOF", "ALLCROSSFILTERED",
})
_ITERATOR_CALLS = frozenset({
    "SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "PRODUCTX", "MEDIANX", "CONCATENATEX", "FILTER", "ADDCOLUMNS",
    "SELECTCOLUMNS", "TOPN", "GENERATE", "GENERATEALL", "RANKX", "SUMMARIZE", "GROUPBY", "XNPV",
})


def logical_conjuncts(node: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    """The operands of a top-level && chain or AND(a, b), left to right; any other expression is its own single conjunct."""
    if node[0] == "logical" and node[1] == "&&":
        return logical_conjuncts(node[2]) + logical_conjuncts(node[3])
    if node[0] == "call" and node[1] == "AND" and len(node[2]) == 2:
        return logical_conjuncts(node[2][0]) + logical_conjuncts(node[2][1])
    return [node]


def _consume_infinity(thunk: Any) -> Any:
    """Refuse to let an Infinity/NaN flow into a comparison, ISBLANK or SWITCH.

    Power BI compares Infinity (IF(1/0>1, ...) is true). The local engine has no
    Infinity, so it must not let IFERROR turn that case into a quietly different
    answer; raising a plain MeasureError makes the formula visibly unsupported.
    """
    try:
        return thunk()
    except _DivisionError as exc:
        raise MeasureError(
            "A division by zero feeds a comparison, ISBLANK or SWITCH; Power BI treats it "
            "as Infinity, which the local engine does not model."
        ) from exc


@dataclass(frozen=True)
class VisualAxisContext:
    """The report selection behind one chart category filter."""

    table_id: str
    column: str
    selected_rows: frozenset[int] | None
    blank_allowed: bool | None
    filter_table_ids: frozenset[str]


def _reject_power_query_error(value: Any, column: str, row: int | None) -> None:
    if not is_cell_error(value):
        return
    location = f" at row {row}" if row is not None else ""
    raise MeasureError(
        f"Column {column!r} contains a Power Query cell error{location}: {value.message}. "
        "Remove or replace the error before evaluating this DAX expression."
    )


MAX_MEASURES = 5_000  # Power BI has no measure limit; this only guards the saved file and the refresh time
MAX_CALCULATED_COLUMNS = 500
MAX_EXPRESSION_LENGTH = 50_000
MAX_TOKENS = 5_000

_FUNCTIONS = {
    "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "DISTINCTCOUNT",
    "DISTINCTCOUNTNOBLANK",
    "COUNTROWS", "COUNTX", "COUNTAX", "DIVIDE", "COALESCE", "ABS", "ROUND", "IF", "AND", "OR", "NOT",
    "INT", "TRUNC", "SIGN", "SQRT", "EXP", "LN", "MOD", "POWER", "CEILING", "FLOOR",
    "ISBLANK", "IFERROR", "SWITCH", "MEDIAN", "PRODUCT", "COUNTBLANK",
    "SUMX", "AVERAGEX", "MAXX", "MINX", "TOTALYTD", "TOTALQTD", "TOTALMTD",
    "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN", "DATESINPERIOD",
    "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH", "PREVIOUSDAY",
    "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
    "PARALLELPERIOD",
    "DATEADD", "SAMEPERIODLASTYEAR", "CALCULATE", "KEEPFILTERS", "FILTER",
    "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED",
    "USERELATIONSHIP", "CROSSFILTER", "RELATED",
}
# Text, information and conversion functions evaluated by analytics_studio.dax_typed (min, max arguments).
_TYPED_ARITY = {
    "CONCATENATE": (2, 2), "LEN": (1, 1), "UPPER": (1, 1), "LOWER": (1, 1), "TRIM": (1, 1),
    "LEFT": (1, 2), "RIGHT": (1, 2), "MID": (3, 3), "SUBSTITUTE": (3, 4), "REPLACE": (4, 4),
    "REPT": (2, 2), "FIND": (2, 4), "SEARCH": (2, 4), "EXACT": (2, 2), "VALUE": (1, 1),
    "FIXED": (1, 3), "FORMAT": (2, 3), "UNICHAR": (1, 1), "UNICODE": (1, 1), "ISERROR": (1, 1), "ISNUMBER": (1, 1),
    "ISTEXT": (1, 1), "ISNONTEXT": (1, 1), "ISLOGICAL": (1, 1),
    "DATE": (3, 3), "TIME": (3, 3), "YEAR": (1, 1), "MONTH": (1, 1), "DAY": (1, 1), "HOUR": (1, 1),
    "MINUTE": (1, 1), "SECOND": (1, 1), "QUARTER": (1, 1), "WEEKDAY": (1, 2), "WEEKNUM": (1, 2),
    "EOMONTH": (2, 2), "EDATE": (2, 2), "DATEDIFF": (3, 3), "DATEVALUE": (1, 1), "TIMEVALUE": (1, 1),
    "TODAY": (0, 0), "NOW": (0, 0), "CONVERT": (2, 2),
}
_TYPED_ARITY.update(dax_math.MATH_ARITY)
_TYPED_ARITY["ISO.CEILING"] = (1, 2)
_TYPED_ARITY.update(dax_ext.ARITY)
_FUNCTIONS |= set(_TYPED_ARITY) | dax_math.STAT_COLUMN_FUNCTIONS | dax_math.STAT_PERCENTILE_COLUMN | dax_math.STAT_ITERATORS
_ALL_ITERATORS = {"SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX"} | dax_math.STAT_ITERATORS
_DATE_FUNCTIONS = {
    "DATE", "TIME", "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "QUARTER", "WEEKDAY", "WEEKNUM", "EOMONTH",
    "EDATE", "DATEDIFF", "DATEVALUE", "TIMEVALUE", "TODAY", "NOW",
}
_COLUMN_SCALAR_ARITY = {"SELECTEDVALUE": (1, 2), "HASONEVALUE": (1, 1)}
_ROW_ORDER_FUNCTIONS = frozenset({
    "CONCATENATEX", "TOPN", "TOPNSKIP", "INDEX", "OFFSET", "WINDOW", "FIRSTNONBLANK", "LASTNONBLANK", "RANKX", "GENERATE", "GENERATEALL",
})
_FUNCTIONS |= set(_COLUMN_SCALAR_ARITY) | {
    "CONCATENATEX", "XNPV", "IF.EAGER", "ERROR", "CUSTOMDATA", "NAMEOF", "EVALUATEANDLOG", "ALLCROSSFILTERED",
}
# Lookup, membership, filter-context and table-constructor functions (min, max arguments; None is unbounded).
_LOOKUP_ARITY = {
    "CONTAINS": (3, None), "CONTAINSROW": (2, None), "LOOKUPVALUE": (3, None), "ISEMPTY": (1, 1),
    "ISFILTERED": (1, 1), "ISCROSSFILTERED": (1, 1), "HASONEFILTER": (1, 1), "ISINSCOPE": (1, 1),
    "COMBINEVALUES": (3, None), "USERNAME": (0, 0), "USERPRINCIPALNAME": (0, 0), "FIRSTNONBLANK": (2, 2),
    "LASTNONBLANK": (2, 2), "FIRSTNONBLANKVALUE": (2, 2), "LASTNONBLANKVALUE": (2, 2), "GENERATESERIES": (2, 3),
    "ROW": (2, None),
}
_FUNCTIONS |= set(_LOOKUP_ARITY)
# Table-valued functions (min, max arguments) and the rank / outer-row functions.
_TABLE_FUNCTION_ARITY = {
    "ADDCOLUMNS": (3, None), "SELECTCOLUMNS": (2, None), "SUMMARIZE": (2, None), "TOPN": (2, None),
    "UNION": (2, None), "EXCEPT": (2, 2), "INTERSECT": (2, 2), "CROSSJOIN": (2, None), "CALCULATETABLE": (1, None),
    "SUMMARIZECOLUMNS": (1, None), "GROUPBY": (2, None), "TREATAS": (2, None), "NATURALINNERJOIN": (2, 2),
    "NATURALLEFTOUTERJOIN": (2, 2), "SAMPLE": (3, None), "GENERATE": (2, 2), "GENERATEALL": (2, 2),
    "DATATABLE": (3, None), "CALENDAR": (2, 2), "TOPNSKIP": (3, None), "FILTERS": (1, 1),
    "INDEX": (1, 7), "OFFSET": (1, 7), "WINDOW": (2, 10), "TABLEOF": (1, 1),
}
# only meaningful inside SUMMARIZECOLUMNS (IGNORE, NONVISUAL) and GROUPBY (CURRENTGROUP); elsewhere they raise
_FUNCTIONS |= {"IGNORE", "NONVISUAL", "CURRENTGROUP"}
_NEW_TABLE_FUNCTIONS = {
    "SUMMARIZECOLUMNS", "GROUPBY", "TREATAS", "NATURALINNERJOIN", "NATURALLEFTOUTERJOIN", "SAMPLE", "GENERATE",
    "GENERATEALL", "DATATABLE", "CALENDAR", "TOPNSKIP", "FILTERS", "INDEX", "OFFSET", "WINDOW",
}
_RANK_ARITY = {
    "RANKX": (2, 5), "RANK.EQ": (2, 3), "EARLIER": (1, 2), "EARLIEST": (1, 1), "RANK": (0, 7), "ROWNUMBER": (0, 6),
}
_WINDOW_SCALARS = {"RANK", "ROWNUMBER"}
_FUNCTIONS |= {"ORDERBY", "PARTITIONBY", "MATCHBY"}
_FUNCTIONS |= set(_TABLE_FUNCTION_ARITY) | set(_RANK_ARITY)
_FUNCTIONS |= dax_time_sets.SET_FUNCTIONS | dax_time_sets.BALANCES  # date sets and balances (iteration 84)
_FUNCTIONS.add("RELATEDTABLE")
_TABLE_FIRST_PARENTS = _ALL_ITERATORS | dax_time_sets.SET_FUNCTIONS | {"FIRSTNONBLANK", "LASTNONBLANK", "FIRSTNONBLANKVALUE", "LASTNONBLANKVALUE"} | {
    "COUNTROWS", "CONCATENATEX", "XNPV", "ISEMPTY", "CONTAINS", "CONTAINSROW", "ADDCOLUMNS", "SELECTCOLUMNS", "SUMMARIZE",
    "FILTER", "RANKX", "CALCULATETABLE", "DISTINCT", "VALUES", "FILTERS",
}
_TABLE_ANY_PARENTS = {
    "UNION", "EXCEPT", "INTERSECT", "CROSSJOIN", "SUMMARIZECOLUMNS", "GROUPBY", "TREATAS", "NATURALINNERJOIN",
    "NATURALLEFTOUTERJOIN", "GENERATE", "GENERATEALL", "INDEX", "OFFSET", "WINDOW", "RANK", "ROWNUMBER",
}


def _table_position(parent_function: str, argument_index: int) -> bool:
    """Whether an argument slot of a function takes a table expression."""
    return (
        (parent_function in _TABLE_FIRST_PARENTS and argument_index == 0)
        or (parent_function == "CALCULATE" and argument_index >= 1)
        or (parent_function == "SAMPLE" and argument_index == 1)
        or (parent_function == "TOPNSKIP" and argument_index == 2)
        or parent_function in _TABLE_ANY_PARENTS
        or (parent_function == "TOPN" and argument_index == 1)
        or (parent_function == "EVALUATEANDLOG" and argument_index == 0)
    )


_TABLE_BUILDING_CALLS = frozenset({
    "UNION", "CROSSJOIN", "GENERATESERIES", "TREATAS", "NATURALINNERJOIN", "NATURALLEFTOUTERJOIN", "GENERATE", "GENERATEALL", "DATATABLE", "CALENDAR",
    "DISTINCT", "VALUES", "ROW", "CALENDARAUTO",
})
_BOOLEAN_INFO_CALLS = frozenset({"CONTAINS", "CONTAINSROW", "ISEMPTY", "ISFILTERED", "ISINSCOPE", "HASONEFILTER", "ISCROSSFILTERED"})
_TYPED_RESULT_CATEGORY = {
    **dict.fromkeys(
        ["CONCATENATE", "UPPER", "LOWER", "TRIM", "LEFT", "RIGHT", "MID", "SUBSTITUTE", "REPLACE", "REPT", "FIXED", "FORMAT", "UNICHAR"],
        "text",
    ),
    **dict.fromkeys(["EXACT", "ISERROR", "ISNUMBER", "ISTEXT", "ISNONTEXT", "ISLOGICAL", "ISEVEN", "ISODD"], "boolean"),
    **dict.fromkeys(["DATE", "TIME", "EOMONTH", "EDATE", "DATEVALUE", "TIMEVALUE", "TODAY", "NOW"], "date/time"),
    **dax_ext.CATEGORY,
}
# These literal/table forms have local parser support outside ``_FUNCTIONS``.
# Keep them in the editor picker so the visible catalog matches what the local
# evaluator can recognize.
DAX_FUNCTION_NAMES = tuple(sorted(_FUNCTIONS | {"BLANK", "DISTINCT", "FALSE", "TRUE", "VALUES"}))
_MAX_DATE_SERIAL = dax_dates.from_datetime(datetime(9999, 12, 31, 23, 59, 59))
_TIME_FILTER_FUNCTIONS = {
    "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
    "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
    "PARALLELPERIOD",
    "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN",
    "DATESINPERIOD",
}
_CROSSFILTER_DIRECTIONS = {
    "NONE", "BOTH", "ONEWAY", "ONEWAY_LEFTFILTERSRIGHT",
    "ONEWAY_RIGHTFILTERSLEFT",
}
_TOKEN_PATTERN = re.compile(
    r"(?P<table_ref>'(?:[^']|'')+'\s*\[(?:[^\]]|\]\])+\]|[A-Za-z_][A-Za-z0-9_]*\s*\[(?:[^\]]|\]\])+\])"
    r"|(?P<table_name>'(?:[^']|'')+')"
    r"|(?P<ref>\[(?:[^\]\r\n]|\]\])+\])"
    r"|(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r'|(?P<string>"(?:[^"]|"")*")'
    r"|(?P<identifier>[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z][A-Za-z0-9_]*|2T\b))*)"
    r"|(?P<operator><>|<=|>=|==|&&|\|\||[(){}+\-*/,=<>&^])"
)
_FORMULA_ASSIGNMENT = re.compile(
    r"^\s*(?:\[(?P<bracketed>(?:[^\]\r\n]|\]\])+)\]|"
    r"(?P<plain>(?!VAR\b)(?!\d+\s*=)(?!NOT\s+[\d\"'+\-.])[A-Za-z_][^()\[\],<>!+=*/&^\"\r\n]*?))\s*=\s*(?![=<>])"
)


def escape_bracket_name(name: str) -> str:
    """The text between the brackets of ``[name]``: a closing bracket in the name is written twice (``]]``)."""
    return name.replace("]", "]]")


@dataclass(frozen=True)
class Token:
    kind: str
    value: str


_DAX_WHITESPACE = " \t\r\n"  # the only characters Power BI skips between tokens (not NBSP, U+2003, U+3000, ...)


def _comment_end(expression: str, position: int) -> int | None:
    """Where the DAX comment that starts at `position` ends, or None when none starts there. Line comments (// and --)
    run to the end of the line; block comments nest (Power BI: `5 /* /* */ */ + 1` is 6, `5 /* /* */ + 1` is an error)."""
    if expression.startswith(("//", "--"), position):
        cr = expression.find("\r", position)
        lf = expression.find("\n", position)
        if cr >= 0 and lf >= 0:
            return min(cr, lf)
        if cr >= 0:
            return cr
        if lf >= 0:
            return lf
        return len(expression)
    if not expression.startswith("/*", position):
        return None
    depth, cursor = 0, position
    while cursor < len(expression):
        if expression.startswith("/*", cursor):
            depth += 1
            cursor += 2
        elif expression.startswith("*/", cursor):
            depth -= 1
            cursor += 2
            if depth == 0:
                return cursor
        else:
            cursor += 1
    raise MeasureError("A /* comment is not closed.")


_BRACKET_NAME = re.compile(r"\[(?:[^\]]|\]\])+\]")


def _reference_after_comments(expression: str, position: int) -> tuple[str, int] | None:
    """When only blanks and at least one comment separate `position` from a `[column]`, that bracketed name and where it ends."""
    cursor, skipped_comment = position, False
    while cursor < len(expression):
        if expression[cursor] in _DAX_WHITESPACE:
            cursor += 1
            continue
        try:
            comment_end = _comment_end(expression, cursor)
        except MeasureError:
            return None
        if comment_end is None:
            break
        skipped_comment = True
        cursor = comment_end
    if not skipped_comment or cursor >= len(expression) or expression[cursor] != "[":
        return None
    match = _BRACKET_NAME.match(expression, cursor)
    return None if match is None else (match.group(), match.end())


def _blank_with_comment_end(expression: str, position: int) -> int | None:
    """When BLANK( is followed by comments before ), return position after ) else None."""
    cursor = position
    while cursor < len(expression) and expression[cursor] in _DAX_WHITESPACE:
        cursor += 1
    if cursor >= len(expression) or expression[cursor] != "(":
        return None
    cursor += 1
    had_comment = False
    while cursor < len(expression):
        if expression[cursor] in _DAX_WHITESPACE:
            cursor += 1
            continue
        comment_end = _comment_end(expression, cursor)
        if comment_end is not None:
            had_comment = True
            cursor = comment_end
            continue
        if expression[cursor] == ")" and had_comment:
            return cursor + 1
        break
    return None


def tokenize(expression: str) -> list[Token]:
    if not isinstance(expression, str) or not expression.strip():
        raise MeasureError("Enter a DAX expression.")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise MeasureError(f"A DAX expression can contain at most {MAX_EXPRESSION_LENGTH:,} characters.")
    tokens: list[Token] = []
    position = 0
    while position < len(expression):
        if expression[position] in _DAX_WHITESPACE:
            position += 1
            continue
        comment_end = _comment_end(expression, position)
        if comment_end is not None:
            position = comment_end
            continue
        match = _TOKEN_PATTERN.match(expression, position)
        if match is None:
            raise MeasureError(f"Unsupported character at position {position + 1}.")
        kind = match.lastgroup or ""
        value = match.group()
        if kind in {"identifier", "table_name"}:
            if kind == "identifier" and value.upper() == "BLANK":
                blank_comment_end = _blank_with_comment_end(expression, match.end())
                if blank_comment_end is not None:
                    tokens.append(Token("blank_comment", "BLANK"))
                    position = blank_comment_end
                    continue
            joined = _reference_after_comments(expression, match.end())
            if joined is not None and not (kind == "identifier" and value.upper() == "NOT"):
                # live Power BI (iteration 88): comments between a table name and its [column] are skipped like blanks (Facts/*c*/[Quantity])
                column_text, end = joined
                table_text = value[1:-1].replace("''", "'") if kind == "table_name" else value
                column = column_text[1:-1].replace("]]", "]")
                if not column.strip():
                    raise MeasureError("A column reference cannot be empty.")
                tokens.append(Token("reference", f"{table_text}\0{column}"))
                position = end
                continue
        if kind == "table_name":
            tokens.append(Token("table", value[1:-1].replace("''", "'")))
        elif kind in {"ref", "table_ref"}:
            # kept exactly as written (Power BI does not trim [ Quantity ]); a doubled ']' is one ']' of the name
            column = value[_qualified_column_start(value) + 1:-1].replace("]]", "]")
            if not column.strip():
                raise MeasureError("A column reference cannot be empty.")
            table = _qualified_table_name(value) if kind == "table_ref" else ""
            if table.upper() == "NOT" and not value.startswith("'"):  # NOT [Measure]: a negation, not a table called NOT
                tokens.append(Token("identifier", "NOT"))
                table = ""
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


def _qualified_table_name(value: str) -> str:
    """Read a quoted or unquoted table name before its column reference."""
    if value.startswith("'"):
        position = 1
        while position < len(value):
            if value[position] != "'":
                position += 1
                continue
            if position + 1 < len(value) and value[position + 1] == "'":
                position += 2
                continue
            return value[1:position].replace("''", "'")
        return value[1:].replace("''", "'")
    return value.split("[", 1)[0].strip()


def _qualified_column_start(value: str) -> int:
    """Return the opening bracket of a column in a qualified reference."""
    if value.startswith("'"):
        position = 1
        while position < len(value):
            if value[position] != "'":
                position += 1
                continue
            if position + 1 < len(value) and value[position + 1] == "'":
                position += 2
                continue
            opening = value.find("[", position + 1)
            return opening if opening >= 0 else len(value)
    opening = value.find("[")
    return opening if opening >= 0 else len(value)


def rename_table_references(expression: str, old_name: str, new_name: str) -> str:
    """Rename lexical DAX table references without changing quoted string values."""
    if not isinstance(expression, str):
        raise MeasureError("A DAX expression must be text.")
    if not old_name or not new_name or old_name.casefold() == new_name.casefold():
        return expression
    output: list[str] = []
    position = 0
    while position < len(expression):
        try:
            comment_end = _comment_end(expression, position)
        except MeasureError:
            comment_end = len(expression)  # an unterminated comment: leave the rest as written
        if comment_end is not None:
            output.append(expression[position:comment_end])
            position = comment_end
            continue
        match = _TOKEN_PATTERN.match(expression, position)
        if match is None:
            output.append(expression[position])
            position += 1
            continue
        token = match.group()
        kind = match.lastgroup
        if kind in {"table_ref", "table_name"}:
            bracket_at = _qualified_column_start(token) if kind == "table_ref" else len(token)
            prefix = token[:bracket_at]
            table_text = prefix.strip()
            if table_text.startswith("'") and table_text.endswith("'"):
                table_name = table_text[1:-1].replace("''", "'")
            else:
                table_name = table_text
            if table_name.casefold() == old_name.casefold():
                spacing = prefix[len(prefix.rstrip()):]
                quoted_name = "'" + new_name.replace("'", "''") + "'"
                token = quoted_name + spacing + token[bracket_at:]
        output.append(token)
        position = match.end()
    return "".join(output)


def _parse_year_end_date(value: Any) -> tuple[int, int]:
    """The month and day of a year-end text, as Power BI reads them (iteration 84, live): the one parser of dax_time_sets, shared with
    STARTOFYEAR / ENDOFYEAR / NEXTYEAR, so the same text gives the same year end in TOTALYTD and in the date sets."""
    if not isinstance(value, str):
        raise MeasureError('year_end_date must use month/day, such as "6/30".')
    try:
        return dax_time_sets.parse_year_end_text(value)
    except dax_time_sets.TimeSetError as error:
        raise MeasureError('year_end_date must be a valid month/day, such as "6/30".') from error


_LINEAGE_WIPE_TABLES = frozenset({"UNION", "EXCEPT", "INTERSECT", "TOPN", "SELECTCOLUMNS", "ADDCOLUMNS", "SUMMARIZE", "CALCULATETABLE"})
_NONBLANK_TABLES = {"FIRSTNONBLANK", "LASTNONBLANK"}  # one-row tables; the ...VALUE variants are scalars
_TIME_SET_ARITY = {
    **dict.fromkeys(dax_time_sets.SET_FUNCTIONS, (1, 1)), **dict.fromkeys(dax_time_sets.YEAR_END_FUNCTIONS, (1, 2)),
    "DATESBETWEEN": (3, 3),
}


def _time_set_call_is_new_form(function: str, arguments: list[tuple[Any, ...]]) -> bool:
    """The functions of iteration 84 and the table / nested forms of the older ones are checked by _validate_time_set_call; the older
    functions keep their long-standing messages for the shapes they always refused (wrong arity, a non-column argument)."""
    if function not in _TIME_FILTER_FUNCTIONS:
        return True
    if function in dax_time_sets.YEAR_END_FUNCTIONS and len(arguments) == 2 and arguments[0][0] == "reference" and arguments[1][0] in {"number", "unary", "boolean", "blank"}:
        return True  # a year end given as a date serial (630 is Sep 21), TRUE() or BLANK()
    return bool(arguments) and arguments[0][0] in {"call", "table_call", "var"} and _TIME_SET_ARITY[function][0] <= len(arguments) <= _TIME_SET_ARITY[function][1]


def _validate_time_set_call(function: str, arguments: list[tuple[Any, ...]]) -> None:
    """Arity and argument kinds of the date-set functions (iteration 84); the date argument is a column or a table expression."""
    low, high = _TIME_SET_ARITY[function]
    if not low <= len(arguments) <= high or any(argument[0] == "omitted" for argument in arguments):
        raise MeasureError(f"{function} has the wrong number of arguments.")
    if arguments[0][0] in {"number", "string", "boolean", "blank", "unary", "binary", "arithmetic"}:
        raise MeasureError(f"{function} needs a date column or a table expression of dates.")
    if function == "DATESBETWEEN" and arguments[0][0] != "reference":
        # live Power BI: "DatesBetween and DatesInPeriod functions are only accepting date column reference as a first argument"
        raise MeasureError("DATESBETWEEN accepts only a date column reference as its first argument.")


def _first_reference(node: Any, held: Callable[[str], Any] | None = None) -> tuple[Any, ...] | None:
    """The column reference at the bottom of the first-argument chain of a date-set call (ENDOFMONTH(PREVIOUSMONTH(Date)),
    LASTDATE(CALCULATETABLE(VALUES(Date), ..)), FIRSTDATE(FILTER(ALL(Date), ..)))."""
    for _step in range(64):
        if not isinstance(node, tuple) or not node:
            return None
        if node[0] == "reference":
            return node
        if node[0] == "var" and held is not None:
            node = held(node[1])  # a VAR holding a date set: the column it came from
        elif node[0] == "table_call":
            node = node[2]
        elif node[0] == "call" and node[2]:
            node = node[2][0]
        else:
            return None
    return None


def _legacy_time_shape(node: tuple[Any, ...]) -> bool:
    """A time-intelligence filter in the form the long-standing CALCULATE ladder handles: a column reference and constant arguments."""
    function, arguments = node[1], node[2]
    if function not in _TIME_FILTER_FUNCTIONS or not arguments or arguments[0][0] != "reference":
        return False
    if function in {"PREVIOUSYEAR", "NEXTYEAR", "DATESYTD"}:
        return len(arguments) == 1 or (len(arguments) == 2 and arguments[1][0] == "string")
    if function == "DATESBETWEEN":
        return len(arguments) == 3 and arguments[1][0] in {"string", "blank"} and arguments[2][0] in {"string", "blank"}
    return len(arguments) == 1 or function not in dax_time_sets.SET_FUNCTIONS


def _is_late_time_set(node: Any) -> bool:
    """Live Power BI: a date-set call whose first argument is, through any chain of date-set calls, a bare column reads that
    column AFTER the row-to-filter transition of the CALCULATE (everything else in the filter arguments is read before it)."""
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] in dax_time_sets.SET_FUNCTIONS and node[2]):
        return False
    for _step in range(64):
        if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[2]
                and (node[1] in dax_time_sets.SET_FUNCTIONS or node[1] in _NONBLANK_TABLES)):
            return False
        node = node[2][0]
        if node[0] == "reference":
            return True
    return False


def _late_chain_reads_data_expression(node: Any) -> bool:
    """A FIRSTNONBLANK / LASTNONBLANK inside a late date-set chain whose expression is not a constant: its expression would be read
    before the transition in Power BI, which the chain does not do here."""
    for _step in range(64):
        if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[2]):
            return False
        if node[1] in _NONBLANK_TABLES and node[2][1][0] not in {"number", "string", "boolean", "blank"}:
            return True
        node = node[2][0]
    return False


def _is_late_nonblank(node: Any) -> bool:
    return (
        isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] in _NONBLANK_TABLES
        and bool(node[2]) and node[2][0][0] == "reference"
    )


def _new_route_time_set(node: Any) -> bool:
    """A date-set call the table path evaluates (everything the old ladder does not take)."""
    return (
        isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] in dax_time_sets.SET_FUNCTIONS
        and (node[1] not in _TIME_FILTER_FUNCTIONS or not _legacy_time_shape(node))
    )


def _check_set_iterator_body(table: tuple[Any, ...], body: tuple[Any, ...]) -> None:
    """Live Power BI: an iterator over a date set (or FIRSTNONBLANK ..) reads only the set's own column; any other qualified column in
    the body is an error at compile time, also when the set turns out to be empty."""
    if not (table[0] == "call" and (table[1] in dax_time_sets.SET_FUNCTIONS or table[1] in _NONBLANK_TABLES or table[1] in _TIME_FILTER_FUNCTIONS
                                   or (table[1] in {"UNION", "EXCEPT", "INTERSECT"} and table[2] and table[2][0][0] == "call"
                                       and (table[2][0][1] in dax_time_sets.SET_FUNCTIONS or table[2][0][1] in _TIME_FILTER_FUNCTIONS)))):
        return
    bottom = _first_reference(table)
    if bottom is None or not bottom[1]:
        return
    for reference in _direct_column_references(body):
        if reference[1] and (reference[1].casefold(), reference[2].casefold()) != (bottom[1].casefold(), bottom[2].casefold()):
            raise MeasureError("The iterated date set has one column; the expression reads another column.")


def _check_single_column_filter(table: tuple[Any, ...], predicate: tuple[Any, ...]) -> None:
    """FILTER(VALUES(T[c]), ..) and FILTER(ALL(T[c]), ..) hold one column: Power BI rejects a predicate that reads another qualified
    column at compile time, also when the filtered table is empty."""
    if table[0] == "table_call" and table[2][0] == "reference":
        column = table[2]
    elif table[0] == "call" and table[1] in {"ALL", "ALLNOBLANKROW"} and len(table[2]) == 1 and table[2][0][0] == "reference":
        column = table[2][0]
    else:
        return
    if not column[1]:
        return
    for reference in _direct_column_references(predicate):
        if reference[1] and (reference[1].casefold(), reference[2].casefold()) != (column[1].casefold(), column[2].casefold()):
            raise MeasureError("A FILTER over one column cannot read another column in its condition.")


def _balance_call(function: str, arguments: list[tuple[Any, ...]]) -> tuple[Any, ...]:
    """OPENINGBALANCEx(e, d, f) is CALCULATE(e, PREVIOUSDAY(STARTOFx(d)), f); CLOSINGBALANCEx(e, d, f) is CALCULATE(e, ENDOFx(d), f)
    (live Power BI: 800 random probes). The YEAR forms take the year end as the fourth argument."""
    unit = next(candidate for candidate in ("MONTH", "QUARTER", "YEAR") if function.endswith(candidate))
    if not 2 <= len(arguments) <= (4 if unit == "YEAR" else 3) or any(argument[0] == "omitted" for argument in arguments[:2]):
        raise MeasureError(f"{function} has the wrong number of arguments.")
    if len(arguments) > 2 and arguments[2][0] == "omitted":
        raise MeasureError(f"Argument '3' of {function} is required.")
    if len(arguments) == 4 and arguments[3][0] == "omitted":
        raise MeasureError(f"{function} has the wrong number of arguments.")
    if arguments[1][0] in {"number", "string", "boolean", "blank"}:
        raise MeasureError(f"{function} needs a date column or a table expression of dates.")
    edge = ("call", ("START" if function.startswith("OPENING") else "END") + "OF" + unit,
            (arguments[1],) + ((arguments[3],) if len(arguments) == 4 else ()))
    if function.startswith("OPENING"):
        edge = ("call", "PREVIOUSDAY", (edge,))
    return ("call", "CALCULATE", (arguments[0], edge) + ((arguments[2],) if len(arguments) > 2 else ()))


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
    current_year_end = dax_time_sets._year_end_of(end_date.year, year_end)  # a Feb 29 year end is Mar 1 in a common year (live Power BI)
    if end_date > current_year_end:
        return current_year_end + timedelta(days=1)
    if end_date.year > date.min.year:
        return dax_time_sets._year_end_of(end_date.year - 1, year_end) + timedelta(days=1)
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


def _previousday_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date]
) -> set[date]:
    selected = tuple(selected_dates)
    if not selected:
        return set()
    try:
        target = min(selected) - timedelta(days=1)
    except OverflowError:
        return set()
    return {value for value in available_dates if value == target}


def _nextday_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date]
) -> set[date]:
    selected = tuple(selected_dates)
    if not selected:
        return set()
    try:
        target = max(selected) + timedelta(days=1)
    except OverflowError:
        return set()
    return {value for value in available_dates if value == target}


def _nextmonth_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date]
) -> set[date]:
    selected = tuple(selected_dates)
    if not selected:
        return set()
    last_date = max(selected)
    target_year, target_month = last_date.year, last_date.month + 1
    if target_month > 12:
        target_year += 1
        target_month = 1
    try:
        start = date(target_year, target_month, 1)
        end = date(target_year, target_month, monthrange(target_year, target_month)[1])
    except ValueError:
        return set()
    return {value for value in available_dates if start <= value <= end}


def _nextquarter_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date]
) -> set[date]:
    selected = tuple(selected_dates)
    if not selected:
        return set()
    last_date = max(selected)
    q_start_month = ((last_date.month - 1) // 3) * 3 + 1
    target_month = q_start_month + 3
    target_year = last_date.year
    if target_month > 12:
        target_year += 1
        target_month -= 12
    try:
        start = date(target_year, target_month, 1)
        end_month = target_month + 2
        end = date(target_year, end_month, monthrange(target_year, end_month)[1])
    except ValueError:
        return set()
    return {value for value in available_dates if start <= value <= end}


def _nextyear_dates(
    selected_dates: Iterable[date],
    available_dates: Iterable[date],
    year_end: tuple[int, int] = (12, 31),
) -> set[date]:
    selected = tuple(selected_dates)
    if not selected:
        return set()
    last_date = max(selected)
    current_year_start = _year_to_date_start(last_date, year_end)
    if current_year_start == date.min:
        return set()
    try:
        next_year_start = _year_to_date_start(current_year_start + timedelta(days=366), year_end)
        next_year_end = _year_to_date_start(next_year_start + timedelta(days=366), year_end) - timedelta(days=1)
    except (OverflowError, ValueError):
        return set()
    return {value for value in available_dates if next_year_start <= value <= next_year_end}


def _parallelperiod_dates(
    selected_dates: Iterable[date], available_dates: Iterable[date], intervals: int, interval: str
) -> set[date]:
    selected = tuple(selected_dates)
    if not selected:
        return set()
    unit = interval.upper()
    try:
        first_shifted = _dateadd_dates([min(selected)], intervals, unit)
        last_shifted = _dateadd_dates([max(selected)], intervals, unit)
        if not first_shifted or not last_shifted:
            return set()
        
        f = min(first_shifted)
        l = max(last_shifted)
        if unit == "YEAR":
            start = _year_to_date_start(f, (12, 31))
            end = date(l.year, 12, 31)
        elif unit == "QUARTER":
            start = date(f.year, ((f.month - 1) // 3) * 3 + 1, 1)
            l_start_month = ((l.month - 1) // 3) * 3 + 1
            l_end_month = l_start_month + 2
            end = date(l.year, l_end_month, monthrange(l.year, l_end_month)[1])
        elif unit == "MONTH":
            start = date(f.year, f.month, 1)
            end = date(l.year, l.month, monthrange(l.year, l.month)[1])
        else:
            return set()
    except (MeasureError, OverflowError, ValueError):
        return set()
    return {value for value in available_dates if start <= value <= end}


def _is_var_filter_constant(node: Any) -> bool:
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "number":
        return True
    if node[0] == "unary" and node[1] in {"+", "-"} and len(node) >= 3 and node[2][0] == "number":
        return True
    return False


def _unwrap_var_filter(node: tuple[Any, ...], outer: dict[str, tuple[Any, ...]] | None = None) -> tuple[Any, ...]:
    """Replace the variables of a VAR block inside a CALCULATE filter by what they hold (a bare column reference or a
    numeric constant). An inner block may reuse an outer name: the inner value wins inside the inner block only."""
    if not isinstance(node, tuple) or not node or node[0] != "let":
        return node
    bindings, body = node[1], node[2]
    env: dict[str, tuple[Any, ...]] = dict(outer or {})
    for name, value in bindings:
        if not (isinstance(value, tuple) and bool(value) and (value[0] == "reference" or _is_var_filter_constant(value))):
            raise MeasureError("CALCULATE filters must be column comparisons joined with AND, OR, or NOT.")
        env[name] = value
    if isinstance(body, tuple) and body and body[0] == "let":
        return _unwrap_var_filter(body, env)

    def _subst(n: Any) -> Any:
        if not isinstance(n, tuple) or not n:
            return n
        if n[0] == "let":
            raise MeasureError("CALCULATE filters must be column comparisons joined with AND, OR, or NOT.")
        if n[0] == "var" and n[1] in env:
            return env[n[1]]
        return tuple(_subst(child) for child in n)

    return _subst(body)


def _calculate_filter_argument(node: tuple[Any, ...]) -> tuple[tuple[Any, ...], bool]:
    """Unwrap the one supported CALCULATE filter modifier and optional VAR bindings."""
    keep = False
    if node[0] == "call" and node[1] == "KEEPFILTERS":
        if len(node[2]) != 1:
            raise MeasureError("KEEPFILTERS needs one Boolean filter expression.")
        node, keep = node[2][0], True
    if node[0] == "let":
        node = _unwrap_var_filter(node)
        if node[0] == "call" and node[1] == "KEEPFILTERS":
            # live: a VAR block whose RETURN is KEEPFILTERS(..) is an error (KEEPFILTERS(VAR .. RETURN ..) is fine)
            raise MeasureError("CALCULATE filters must be column comparisons joined with AND, OR, or NOT.")
    return node, keep


_FILTER_AGGREGATES = {
    "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTBLANK", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK",
    "MEDIAN", "PRODUCT", "COUNTROWS", "SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CALCULATE",
    "EARLIER", "EARLIEST", "SELECTEDVALUE", "LOOKUPVALUE", "FIRSTNONBLANK", "LASTNONBLANK", "RANKX", "RANK.EQ",
}


def _is_filter_scalar(node: Any) -> bool:
    """Return whether a Boolean filter side is a scalar evaluated once, outside the filtered column's row context.

    Literals, variables and arithmetic, text and logic over them, and aggregations such as AVERAGE(Sales) qualify; a
    bare column reference does not.
    """
    if not isinstance(node, tuple) or not node:
        return False
    kind = node[0]
    if kind in {"number", "string", "boolean", "blank", "var"}:
        return True
    if kind == "unary":
        return _is_filter_scalar(node[2])
    if kind in {"binary", "comparison", "logical"}:
        return _is_filter_scalar(node[2]) and _is_filter_scalar(node[3])
    if kind == "concat":
        return _is_filter_scalar(node[1]) and _is_filter_scalar(node[2])
    if kind == "call":
        if node[1] == "CALCULATE":
            return False  # Power BI does not allow CALCULATE inside a True/False filter expression
        if node[1] in _FILTER_AGGREGATES:
            return True
        return all(_is_filter_scalar(argument) for argument in node[2])
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


def _table_filter_base_name(base: tuple[Any, ...], allow_all_base: bool) -> str | None:
    """Return the loaded table a FILTER reads, or None when the base is unsupported."""
    if base[0] == "table":
        return str(base[1])
    if (
        allow_all_base
        and base[0] == "call"
        and base[1] == "ALL"
        and len(base[2]) == 1
        and base[2][0][0] == "table"
    ):
        return str(base[2][0][1])
    return None


def _validate_table_filter_call(
    node: tuple[Any, ...], allow_all_base: bool = False
) -> None:
    table_name = (
        _table_filter_base_name(node[2][0], allow_all_base) if len(node[2]) == 2 else None
    )
    if table_name is None:
        raise MeasureError(
            "FILTER currently needs a base table name and one row predicate."
        )
    _calculate_table_filter_predicate(node[2][1], table_name)


def _validate_filter_clear_call(node: tuple[Any, ...], function: str) -> None:
    """Validate the local table-or-columns forms of filter-clearing functions."""
    arguments = node[2]
    if function == "ALLCROSSFILTERED":
        if len(arguments) != 1 or arguments[0][0] != "table":
            raise MeasureError("ALLCROSSFILTERED needs one table expression.")
        return
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


def _validate_mixed_filter_clear_calculate(
    arguments: tuple[tuple[Any, ...], ...],
) -> bool:
    """Accept the bounded mixed filter-clear CALCULATE forms."""
    if len(arguments) <= 2:
        return False
    modifiers = [
        (index, argument)
        for index, argument in enumerate(arguments[1:], start=1)
        if argument[0] == "call"
        and argument[1] in {
            "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "ALLCROSSFILTERED",
        }
    ]
    if len(modifiers) != 1:
        return False

    modifier_index, modifier = modifiers[0]
    function = modifier[1]
    if function not in {
        "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "ALLCROSSFILTERED",
    }:
        return False
    if function == "ALLEXCEPT":
        _validate_allexcept_call(modifier)
    else:
        _validate_filter_clear_call(modifier, function)
        if function == "ALLNOBLANKROW" and not modifier[2]:
            raise MeasureError("ALLNOBLANKROW needs a table or column argument.")
    filter_arguments = tuple(
        argument
        for index, argument in enumerate(arguments[1:], start=1)
        if index != modifier_index
    )
    if function == "ALLSELECTED":
        table_filters = [
            argument
            for argument in filter_arguments
            if argument[0] == "call" and argument[1] == "FILTER"
        ]
        if table_filters:
            if len(filter_arguments) != 1:
                raise MeasureError(
                    "A table-valued FILTER must be the only filter argument beside ALLSELECTED."
                )
            _validate_table_filter_call(table_filters[0])
            return True
        for filter_argument in filter_arguments:
            if filter_argument[0] == "call" and filter_argument[1] in _TIME_FILTER_FUNCTIONS:
                _validate_literal_positions(filter_argument)
                continue
            if _contains_function_call(filter_argument, "FILTER"):
                raise MeasureError(
                    "A table-valued FILTER must be the only filter argument beside ALLSELECTED."
                )
            predicate, _keep = _calculate_filter_argument(filter_argument)
            _calculate_boolean_filter_column(predicate)
        return True
    table_filters = [
        argument
        for argument in filter_arguments
        if argument[0] == "call" and argument[1] == "FILTER"
    ]
    if table_filters:
        if len(filter_arguments) != 1:
            raise MeasureError(
                "A table-valued FILTER must be the only filter argument beside a filter-clear modifier."
            )
        _validate_table_filter_call(table_filters[0])
        return True
    for index, filter_argument in enumerate(arguments[1:], start=1):
        if index == modifier_index:
            continue
        if filter_argument[0] == "call" and filter_argument[1] in _TIME_FILTER_FUNCTIONS:
            _validate_literal_positions(filter_argument)
            continue
        if _contains_function_call(filter_argument, "FILTER"):
            raise MeasureError(
                "A table-valued FILTER must be the only filter argument beside a filter-clear modifier."
            )
        predicate, _keep = _calculate_filter_argument(filter_argument)
        _calculate_boolean_filter_column(predicate)
    return True


def _validate_allexcept_call(node: tuple[Any, ...]) -> None:
    """Validate the base-table and same-table base-column ALLEXCEPT form."""
    arguments = node[2]
    if len(arguments) < 2 or arguments[0][0] != "table":
        raise MeasureError(
            "ALLEXCEPT needs one base table followed by one or more qualified columns from that table."
        )
    if any(
        (argument[0] != "reference" or not argument[1]) and argument[0] != "table"
        for argument in arguments[1:]
    ):
        raise MeasureError(
            "ALLEXCEPT keeps qualified base columns or whole tables related to its first table."
        )
    named = [(argument[1].casefold(), argument[2].casefold()) for argument in arguments[1:] if argument[0] == "reference"]
    if len(set(named)) != len(named):
        raise MeasureError("ALLEXCEPT was given the same column more than once.")


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


def _literal_kind(node: tuple[Any, ...]) -> str | None:
    if node[0] in {"number", "string", "boolean"}:
        return node[0]
    if node[0] == "call" and node[1] in {"TRUE", "FALSE"} and not node[2]:
        return "boolean"
    return None


def _membership(value: tuple[Any, ...], table: tuple[Any, ...]) -> tuple[Any, ...]:
    """value IN table: strict membership (BLANK, 0 and "" are different members), evaluated per row."""
    if value[0] != "tuple" and table[0] == "call" and table[1] in {"TOPN", "SELECTCOLUMNS", "SUMMARIZE", "EXCEPT", "INTERSECT"}:
        raise MeasureError(f"IN does not accept the table returned by {table[1]}.")
    return ("in", value, table)


def _mixes_table_and_scalar_branches(function: str, arguments: tuple[Any, ...] | list[Any]) -> bool:
    """IF / SWITCH with a table (CALCULATETABLE, RELATEDTABLE, TOPN...) in one result branch and a scalar (or the implicit
    BLANK) in another: Power BI refuses it when the expression is compiled, even when the branch is never evaluated."""
    if function in {"IF", "IF.EAGER"}:
        branches = list(arguments[1:3]) + [("blank",)] * (3 - len(arguments))
    elif len(arguments) % 2 == 0:  # SWITCH(expression, value, result, ..., default)
        branches = list(arguments[2:-1:2]) + [arguments[-1]]
    else:  # no default: BLANK
        branches = list(arguments[2::2]) + [("blank",)]
    tables = [
        isinstance(b, tuple) and b and (b[0] == "table_call" or (b[0] == "call" and (b[1] == "CALCULATETABLE" or b[1] in _TABLE_FUNCTION_ARITY)))
        for b in branches
    ]
    return any(tables) and not all(tables)


def _is_all_table_value_argument(node: Any) -> bool:
    """Return whether a node is a supported filter-function table value."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "table":
        return True
    if node[0] == "var":
        return True  # a VAR holding a table; checked when it is used
    if node[0] in {"table_call", "tableconstructor"}:
        return True  # VALUES / DISTINCT of a column or table, or {1, 2, 3}
    if node[0] == "call" and node[1] == "CURRENTGROUP":
        return True
    if node[0] == "call" and node[1] in {"GENERATESERIES", "ROW"}:
        return True
    if node[0] == "call" and node[1] == "EVALUATEANDLOG" and node[2]:
        return _is_all_table_value_argument(node[2][0])
    if node[0] == "call" and node[1] in _TIME_FILTER_FUNCTIONS:
        return True  # a date set is a one-column table (live Power BI)
    if node[0] == "call" and node[1] == "FILTER":
        try:
            _validate_table_filter_call(node, allow_all_base=True)
            return True
        except MeasureError:
            return len(node[2]) == 2 and _is_all_table_value_argument(node[2][0])
    if node[0] == "call" and (node[1] in _TABLE_FUNCTION_ARITY or node[1] in dax_time_sets.SET_FUNCTIONS or node[1] in _NONBLANK_TABLES):
        return True
    if node[0] == "call" and node[1] == "ALLEXCEPT":
        try:
            _validate_allexcept_call(node)
        except MeasureError:
            return False
        return True
    if node[0] != "call" or node[1] not in {"ALL", "ALLNOBLANKROW", "ALLSELECTED"} or not node[2]:
        return False
    arguments = node[2]
    if len(arguments) == 1 and arguments[0][0] == "table":
        return True
    if any(argument[0] != "reference" or not argument[1] for argument in arguments):
        return False
    return len({argument[1].casefold() for argument in arguments}) == 1


_HELD_TABLE_CALLS = {"FILTER", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED"}


def _is_held_table_value(node: Any) -> bool:
    """A VAR value that is a table made by FILTER or an ALL-family function (checked where it is evaluated)."""
    return (
        isinstance(node, tuple) and len(node) >= 3 and node[0] == "call"
        and node[1] in _HELD_TABLE_CALLS and _is_all_table_value_argument(node)
    )


def _has_supported_all_usage(
    node: Any,
    parent_function: str = "",
    argument_index: int = -1,
    parent_argument_count: int = 0,
) -> bool:
    """Validate that each ALL call occupies a supported scalar/table position."""
    if not isinstance(node, tuple) or not node:
        return True
    if node[0] == "in":
        return _has_supported_all_usage(node[1]) and (
            _is_all_table_value_argument(node[2]) or _has_supported_all_usage(node[2], "COUNTROWS", 0, 1)
        )
    if node[0] == "table_call":
        return _table_position(parent_function, argument_index) and _has_supported_all_usage(node[2], node[1], 0, 1)
    if node[0] == "tableconstructor":
        return True
    if node[0] == "let":
        # a VAR holds a table or a scalar; a held table sits in a table position, the RETURN body is checked as usual
        for _name, value in node[1]:
            if _is_all_table_value_argument(value):
                if not _has_supported_all_usage(value, "COUNTROWS", 0, 1):
                    return False
            elif not _has_supported_all_usage(value):
                return False
        return _has_supported_all_usage(node[2])
    if node[0] == "call":
        function, arguments = node[1], node[2]
        if function in _TIME_FILTER_FUNCTIONS and _legacy_time_shape(node) and not _table_position(parent_function, argument_index):
            return False  # a plain PREVIOUSMONTH(Date) as a value stays refused, as it always was
        if function in dax_time_sets.SET_FUNCTIONS or function in _NONBLANK_TABLES:  # a table or, where one value is wanted, that value
            return all(
                _has_supported_all_usage(argument, function, index, len(arguments))
                for index, argument in enumerate(arguments)
            )
        if function in _TABLE_FUNCTION_ARITY:
            if not _table_position(parent_function, argument_index) and not (
                function == "CALCULATETABLE" and parent_function in {"CALCULATE", "CALCULATETABLE"}
            ) and not (parent_function == "CALCULATETABLE" and argument_index >= 1):
                return False
            return all(
                _has_supported_all_usage(argument, function, index, len(arguments))
                for index, argument in enumerate(arguments)
            )
        if function in {
            "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
            "PREVIOUSMONTH", "DATESYTD", "DATESQTD", "DATESMTD",
            "DATESBETWEEN", "DATESINPERIOD",
        }:
            # live Power BI (iteration 84): a date set is a normal CALCULATE filter at any depth (inside SUMX / MAXX / ... too)
            # and a table wherever a table is taken (COUNTROWS, MAXX, ...)
            if not (parent_function in {"CALCULATE", "CALCULATETABLE"} and argument_index >= 1) and not _table_position(parent_function, argument_index):
                return False
            return all(
                _has_supported_all_usage(argument, function, index, len(arguments))
                for index, argument in enumerate(arguments)
            )
        if function == "FILTER":
            if _table_position(parent_function, argument_index):
                return _is_all_table_value_argument(node) and all(
                    _has_supported_all_usage(argument, "FILTER", index, len(arguments))
                    for index, argument in enumerate(arguments)
                    if index == 0
                )
            return (
                parent_function in {"CALCULATE", "CALCULATETABLE"}
                and argument_index > 0
                and (parent_argument_count > 2 or parent_function == "CALCULATETABLE")
            )
        if function == "ALLEXCEPT":
            try:
                _validate_allexcept_call(node)
            except MeasureError:
                return False
            if _table_position(parent_function, argument_index):
                return True
            return (
                parent_function in {"CALCULATE", "CALCULATETABLE"}
                and argument_index == 1
                and parent_argument_count == 2
            ) or (
                parent_function in {"CALCULATE", "CALCULATETABLE"}
                and argument_index > 0
                and parent_argument_count > 2
            )
        if function in {"ALL", "ALLNOBLANKROW", "ALLSELECTED"}:
            try:
                _validate_filter_clear_call(node, function)
                if function == "ALLNOBLANKROW" and not arguments:
                    return False
            except MeasureError:
                return False
            valid_position = (
                parent_function in {"CALCULATE", "CALCULATETABLE"}
                and argument_index == 1
                and parent_argument_count == 2
            ) or (
                parent_function in {"CALCULATE", "CALCULATETABLE"}
                and function in {"ALL", "ALLNOBLANKROW", "ALLSELECTED"}
                and argument_index > 0
                and parent_argument_count > 2
            ) or (
                _table_position(parent_function, argument_index)
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


def _contains_coalesce_in_row_iterator(node: Any) -> bool:
    """Return whether COALESCE occurs inside a local row-iterator expression."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call":
        function, arguments = node[1], node[2]
        if (
            function in _ALL_ITERATORS
            and len(arguments) == 2
            and _contains_function_call(arguments[1], "COALESCE")
        ):
            return True
    return any(
        _contains_coalesce_in_row_iterator(child)
        for child in node[1:]
        if isinstance(child, tuple)
    )


def _is_coalesce_table_argument(node: Any) -> bool:
    """Return whether a COALESCE argument is a table value in this DAX subset."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] in {"table", "table_call"}:
        return True
    return node[0] == "call" and node[1] in {
        "FILTER", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED",
        "DATEADD", "SAMEPERIODLASTYEAR", "PREVIOUSYEAR", "PREVIOUSQUARTER",
        "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTYEAR", "NEXTQUARTER",
        "NEXTMONTH", "NEXTDAY", "PARALLELPERIOD", "DATESYTD", "DATESQTD",
        "DATESMTD", "DATESBETWEEN", "DATESINPERIOD",
    }


def _has_membership_in_computed_table(node: Any) -> bool:
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "in" and node[2][0] == "call" and node[2][1] in {"TOPN", "SELECTCOLUMNS", "SUMMARIZE", "EXCEPT", "INTERSECT"}:
        return True
    return any(_has_membership_in_computed_table(child) for child in node if isinstance(child, tuple))


_AGGREGATING_CALLS = {
    "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTBLANK", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "MEDIAN",
    "PRODUCT", "COUNTROWS", "SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CALCULATE", "SELECTEDVALUE",
    "LOOKUPVALUE", "FIRSTNONBLANK", "LASTNONBLANK", "RANKX", "CONCATENATEX", "XNPV", "VALUES", "DISTINCT", "ALL",
    "ISFILTERED", "HASONEVALUE", "HASONEFILTER", "ISCROSSFILTERED", "ISINSCOPE", *dax_math.STAT_ITERATORS,
}


def _direct_column_references(node: Any) -> Iterable[tuple[Any, ...]]:
    """Column references of a Boolean filter that are not inside an aggregation (those do not pick the filtered column)."""
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "reference":
        yield node
        return
    if node[0] == "call" and node[1] in _AGGREGATING_CALLS and not (node[1] in {"MIN", "MAX"} and len(node[2]) == 2):
        return
    if node[0] == "table_call" or (node[0] == "call" and node[1] == "RELATED"):
        return  # RELATED reads the row of the enclosing iterator: a value, not a column the filter picks
    children = node if isinstance(node[0], tuple) else node[1:]
    for child in children:
        if isinstance(child, tuple):
            yield from _direct_column_references(child)


def _tested_operands_and_results(node: Any) -> tuple[list[Any], list[Any]]:
    """For an IF / SWITCH / IFERROR / COALESCE call: the operands it tests, and the operands it can return."""
    name, args = node[1], list(node[2])
    if name == "IF":
        return args[:1], args[1:]
    if name == "SWITCH":
        remaining = args[1:]
        fallback = [remaining.pop()] if len(remaining) % 2 else []
        return [args[0], *remaining[::2]], [*remaining[1::2], *fallback]
    if name == "IFERROR":
        return args[:1], args
    return args[:-1], args  # COALESCE


_CANNOT_RAISE_CALLS = frozenset({
    "TRUE", "FALSE", "BLANK", "ISBLANK", "UPPER", "LOWER", "LEN", "ABS", "NOT", "AND", "OR", "COUNTROWS", "SUM", "MAX", "MIN", "COUNT", "SELECTEDVALUE", "DATE",
    "IF", "SWITCH", "IFERROR", "COALESCE", "FORMAT", "EDATE", "CALCULATE",
})


def _cannot_raise(node: Any) -> bool:
    """An expression made only of literals, columns and functions that never raise an error on a row (so evaluating it eagerly is harmless)."""
    if not isinstance(node, tuple) or not node:
        return True
    if node[0] in {"number", "string", "boolean", "blank", "reference"}:
        return True
    if node[0] in {"comparison", "logical", "binary", "unary", "concat"}:
        return all(_cannot_raise(child) for child in node[1:] if isinstance(child, tuple))
    if node[0] == "call" and node[1] in _CANNOT_RAISE_CALLS:
        return all(_cannot_raise(child) for child in node[2] if isinstance(child, tuple))
    return False


def _has_false_only_if(node: Any) -> bool:
    """IF(condition, FALSE()) anywhere inside: Power BI folds it to FALSE, which COUNTX counts under an IFERROR (live probes, iteration 87)."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[:1] == ("call",) and node[1] == "IF" and len(node[2]) == 2 and node[2][1] == ("boolean", False):
        return True
    return any(_has_false_only_if(child) for child in node if isinstance(child, tuple))


def _statistic_with_arithmetic(node: Any) -> bool:
    """A statistical function (GEOMEAN, VAR.P, STDEV.S, PERCENTILE.INC ...) and arithmetic (+ - * / ^, unary minus) in the same expression.  Power BI
    computes the statistic as a double: shown with 15 digits and a signed zero, and combined with BLANK in ways the local decimals do not follow
    (live probes, iteration 87), so an iterator body that mixes the two is refused."""
    found_statistic = found_arithmetic = False
    stack = [node]
    while stack:
        item = stack.pop()
        if not isinstance(item, tuple) or not item:
            continue
        if item[0] in {"binary", "unary"}:
            found_arithmetic = True
        if item[:1] == ("call",) and (item[1] in dax_math.STAT_COLUMN_FUNCTIONS or item[1] in dax_math.STAT_PERCENTILE_COLUMN):
            found_statistic = True
        stack.extend(child for child in item if isinstance(child, tuple))
    return found_statistic and found_arithmetic


def _coalesce_with_failing_argument(node: Any) -> bool:
    """A COALESCE anywhere in this expression with an argument other than the last that can raise an error (VALUE of text, ...): Power BI evaluates
    those arguments in an order the local engine does not reproduce (live probes, iteration 87), so the error may or may not surface."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[:1] == ("call",) and node[1] == "COALESCE" and len(node[2]) >= 2 and not all(_cannot_raise(argument) for argument in node[2][:-1]):
        return True
    return any(_coalesce_with_failing_argument(child) for child in node if isinstance(child, tuple))


def _spine_has_coalesce(node: Any) -> bool:
    """A COALESCE with two or more arguments on the result spine (the IF / SWITCH / IFERROR / COALESCE branches that can be returned)."""
    if not isinstance(node, tuple) or node[:1] != ("call",) or node[1] not in {"IF", "SWITCH", "IFERROR", "COALESCE"}:
        return False
    if node[1] == "COALESCE" and len(node[2]) >= 2:
        return True
    return any(_spine_has_coalesce(result) for result in _tested_operands_and_results(node)[1])


def _conditional_is_constant(node: Any) -> bool:
    """Some IF / SWITCH / IFERROR / COALESCE on the result spine of this expression tests nothing that reads a column.  Power BI treats such a
    conditional like any other for the types of its branches, except that COUNTX then counts the True/False values it returns (live probes,
    iteration 87: COUNTX(Facts, IF(TRUE(), TRUE(), 7)) is 6, with a row-dependent condition 3)."""
    if not isinstance(node, tuple) or node[:1] != ("call",) or node[1] not in {"IF", "SWITCH", "IFERROR", "COALESCE"}:
        return False
    tested, results = _tested_operands_and_results(node)
    if not any(next(iter(_direct_column_references(operand)), None) is not None for operand in tested):
        return True
    return any(_conditional_is_constant(result) for result in results)


# Power BI: "A function 'X' has been used in a True/False expression that is used as a table filter expression".
# Verified against 15 functions in tools/parity/dax_battery_boolean_filter_functions.json: the error applies only
# outside an X-iterator (SUMX(TOPN(..),1), SUMX(..,CALCULATE(..)) and SUMX(FILTER(..),1) are all accepted).
_BOOLEAN_FILTER_REFUSED_CALLS = frozenset({
    "CALCULATE", "FILTER", "TOPN", "SELECTCOLUMNS", "LOOKUPVALUE", "ADDCOLUMNS", "SUMMARIZE", "SUMMARIZECOLUMNS",
    "GROUPBY", "EXCEPT", "INTERSECT", "ROW", "SAMPLE", "TOPNSKIP", "RANKX", "FIRSTNONBLANK", "LASTNONBLANK",
    "OFFSET", "WINDOW", "INDEX", "RANK", "ROWNUMBER", "CONTAINS",  # CONTAINS: live probes, iteration 87 (also inside IF and arithmetic)
    "TABLEOF", "ALLCROSSFILTERED",
})
_BOOLEAN_FILTER_X_ITERATORS = frozenset({"SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CONCATENATEX", "XNPV", *dax_math.STAT_ITERATORS})


_BOOLEAN_RESULT_CALLS = frozenset({'AND','OR','NOT','ISBLANK','ISEMPTY','ISFILTERED','ISINSCOPE','HASONEFILTER','ISCROSSFILTERED','HASONEVALUE','CONTAINS','CONTAINSROW','CONTAINSSTRING','ISNUMBER','ISTEXT','ISLOGICAL','ISNONTEXT','ISERROR','ISEVEN','ISODD','EXACT','ISSUBTOTAL'})
_TRANSITION_CALLS = frozenset({"CALCULATE", "CALCULATETABLE"})


def _contains_transition_call(node: Any) -> bool:
    """Whether CALCULATE or CALCULATETABLE (which transition a row context into a filter) appears in this expression."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in _TRANSITION_CALLS:
        return True
    return any(isinstance(child, tuple) and _contains_transition_call(child) for child in node)


def _constant_number(node: Any) -> Decimal | None:
    """The value of an expression made of number literals and + - * only, else None."""
    if not isinstance(node, tuple) or not node:
        return None
    if node[0] == "number":
        return node[1]
    if node[0] == "unary" and node[1] in {"+", "-"}:
        value = _constant_number(node[2])
        return None if value is None else (value if node[1] == "+" else -value)
    if node[0] == "binary" and node[1] in {"+", "-", "*"}:
        left, right = _constant_number(node[2]), _constant_number(node[3])
        if left is None or right is None:
            return None
        return left + right if node[1] == "+" else left - right if node[1] == "-" else left * right
    return None


def _multiplies_by_constant_zero(node: Any) -> bool:
    """x * 0, 0 * x, x * (1 - 1)...  Power BI folds such a product to 0 when it can (live probes, iteration 86: SUMX(Facts, Quantity / Quantity * 0) is 0, the
    0/0 row is not NaN), and does not when a column may be blank; the local engine keeps NaN, so a NaN beside such a product is refused."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "binary" and node[1] == "*" and (_constant_number(node[2]) == 0 or _constant_number(node[3]) == 0):
        return True
    return any(_multiplies_by_constant_zero(child) for child in node if isinstance(child, tuple))


_SAMPLE_STATISTICS = frozenset({"STDEV.S", "VAR.S", "STDEVX.S", "VARX.S"})


def _is_sample_statistic(node: Any) -> bool:
    """The measure is STDEV.S / VAR.S / STDEVX.S / VARX.S itself, or CALCULATE of one."""
    if not (isinstance(node, tuple) and node and node[0] == "call"):
        return False
    if node[1] in _SAMPLE_STATISTICS:
        return True
    return node[1] == "CALCULATE" and bool(node[2]) and _is_sample_statistic(node[2][0])


_FRAME_FUNCTIONS = frozenset({
    "SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CONCATENATEX", "PRODUCTX", "MEDIANX", "FILTER", "ADDCOLUMNS", "SELECTCOLUMNS", "TOPN", "RANKX",
    "GENERATE", "GENERATEALL", "SUMMARIZE", "GEOMEANX", "STDEVX.S", "STDEVX.P", "VARX.S", "VARX.P", "PERCENTILEX.INC", "PERCENTILEX.EXC", "XNPV",
})


def _earlier_too_deep(node: Any, frames: int) -> bool:
    """Whether an EARLIER(col, n) / EARLIEST(col) in this expression has fewer than the row contexts it needs, when `frames` row contexts are open
    around it (the body of a nested iterator opens one more).  Iterators the walk does not know leave a deeper stack than counted, never a shallower."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in {"EARLIER", "EARLIEST"} and node[2]:
        depth = 1
        if node[1] == "EARLIER" and len(node[2]) > 1 and node[2][1][0] == "number":
            depth = int(node[2][1][1])
        return frames <= depth if node[1] == "EARLIER" else frames < 2
    if node[0] == "call" and node[1] in _FRAME_FUNCTIONS and node[2]:
        if node[1] == "XNPV" and len(node[2]) == 4:
            return (
                _earlier_too_deep(node[2][0], frames)
                or _earlier_too_deep(node[2][1], frames + 1)
                or _earlier_too_deep(node[2][2], frames + 1)
                or _earlier_too_deep(node[2][3], frames)
            )
        return _earlier_too_deep(node[2][0], frames) or any(_earlier_too_deep(argument, frames + 1) for argument in node[2][1:])
    return any(_earlier_too_deep(child, frames) for child in node if isinstance(child, tuple))


def _earlier_unreadable(node: Any, frames: list[Any], holds: Callable[[Any, str, str], bool]) -> bool:
    """Whether an EARLIER / EARLIEST directly in this expression (not inside a nested iterator) reads a column that no row context it reaches holds;
    `frames` are the open row contexts, the last (None) the iteration the expression is the body of."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in {"EARLIER", "EARLIEST"} and node[2] and node[2][0][0] == "reference":
        depth = 1
        if node[1] == "EARLIER" and len(node[2]) > 1 and node[2][1][0] == "number":
            depth = int(node[2][1][1])
        remaining = frames[:1] if node[1] == "EARLIEST" else frames[:-depth] if depth >= 1 else []
        return bool(remaining) and not any(frame is not None and holds(frame, node[2][0][1], node[2][0][2]) for frame in remaining)
    if node[0] == "call" and node[1] in _FRAME_FUNCTIONS:
        return False  # a nested iterator opens another row context: not followed
    return any(_earlier_unreadable(child, frames, holds) for child in node if isinstance(child, tuple))


def _calculatetable_hoistable(node: Any) -> bool:
    """Every CALCULATETABLE in this scalar has only plain Boolean filters: Power BI evaluates such a scalar once in the
    outer context. With no filter, or with ALL/REMOVEFILTERS/KEEPFILTERS/... it transitions the row instead
    (tools/parity/dax_battery_sdet_filters.json), which the local engine does not model for a Boolean filter."""
    if not isinstance(node, tuple) or not node:
        return True
    if node[0] == "call" and node[1] == "CALCULATETABLE":
        filters = node[2][1:]
        if not filters or any(not (isinstance(f, tuple) and f and f[0] in {"comparison", "logical"}) for f in filters):
            return False
        if any(_contains_function_call(child, "CALCULATETABLE") for child in node[2] if isinstance(child, tuple)):
            return False  # iteration 86 (live probes): CALCULATETABLE(CALCULATETABLE(Facts, Sales>0), Note="Paid") is not the once-evaluated scalar the hoist assumes
    return all(_calculatetable_hoistable(child) for child in node if isinstance(child, tuple))


def _contains_refused_call_outside_x_iterator(node: Any) -> bool:
    """A function Power BI refuses in a True/False filter, anywhere except inside an X-iterator's arguments."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call":
        if node[1] in _BOOLEAN_FILTER_X_ITERATORS:
            return False
        if node[1] in _BOOLEAN_FILTER_REFUSED_CALLS:
            return True
        if node[1] == "EVALUATEANDLOG" and len(node[2]) > 0 and _is_all_table_value_argument(node[2][0]):
            return True
    return any(isinstance(child, tuple) and _contains_refused_call_outside_x_iterator(child) for child in node)


def _numeric_by_construction(node: Any) -> bool:
    """A call whose result is a number even when it is BLANK (DIVIDE, SUMX, SUM ...): SWITCH compares its type with the subject's."""
    return isinstance(node, tuple) and len(node) > 1 and node[0] == "call" and node[1] in {
        "DIVIDE", "SUMX", "SUM", "AVERAGEX", "AVERAGE", "MAXX", "MINX", "MAX", "MIN", "COUNTX", "COUNTROWS", "COUNT", "DISTINCTCOUNT",
        "TOTALMTD", "TOTALQTD", "TOTALYTD", "CALCULATE",
    }


_UNTAKEN_BRANCH_ERRORS = (
    "Iterator expressions can reference columns from their iterated table only",  # live: a single value for the column cannot be determined
    "cannot validate first",
    "needs a Date or DateTime column",  # TOTALYTD(.., text column)
    "does not exist in table",  # iteration 88: a column of the model that the derived table iterated by VALUES / DISTINCT / SUMMARIZE does not hold (live: the same error)
    "A table variable cannot be used where a single value is expected.",
    "A bare table variable is supported only as the direct argument to COUNTROWS.",
    "XNPV does not support expressions of type string/Boolean/date for the Values argument.",  # iteration 91: a compile-time type error
    "The Rate argument to the XNPV function needs a single value",  # iteration 91: a bare column as the rate is a compile-time error
    "Unexpected value for ORDER argument in ISAFTER function.",  # iteration 92: a bad ORDER value is a compile-time error
    "Unexpected value for ORDER argument in ISONORAFTER function.",
)


def _calls_function(node: Any, name: str) -> bool:
    """Whether a call to ``name`` appears anywhere inside the expression tree."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] == name:
        return True
    children = node if isinstance(node[0], tuple) else node[1:]
    return any(_calls_function(child, name) for child in children if isinstance(child, tuple))


_XNPV_LAST_DAY = 2958465  # 9999-12-31: Power BI answers erratically for later dates (probed in iteration 91), so the local engine refuses them


def _bare_column_as_table(node: Any) -> bool:
    """Whether TOPN / FILTER / an X-iterator is given a plain column where a table belongs (Power BI: a single value for the column cannot be determined)."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call":
        position = 1 if node[1] == "TOPN" else 0 if node[1] in {"FILTER", "SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CONCATENATEX"} else None
        if position is not None and len(node[2]) > position and isinstance(node[2][position], tuple) and node[2][position][0] == "reference" and node[2][position][1]:
            return True
    children = node if isinstance(node[0], tuple) else node[1:]
    return any(_bare_column_as_table(child) for child in children if isinstance(child, tuple))


def _keepfilters_inside_time_function(node: Any) -> bool:
    """Whether KEEPFILTERS sits inside a date-set function (PREVIOUSQUARTER(KEEPFILTERS(Cal[Date]))): a Power BI error wherever it is written."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in _TIME_FILTER_FUNCTIONS and any(
        isinstance(argument, tuple) and argument[:2] == ("call", "KEEPFILTERS") for argument in node[2]
    ):
        return True
    children = node if isinstance(node[0], tuple) else node[1:]
    return any(_keepfilters_inside_time_function(child) for child in children if isinstance(child, tuple))


def _iterator_body_reads_a_table_column(node: Any) -> bool:
    """Whether an X-iterator anywhere in this expression has a body that reads a column by table name outside an aggregation."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in {"SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CONCATENATEX"} and len(node[2]) >= 2:
        if any(reference[1] for reference in _direct_column_references(node[2][1])):
            return True
    children = node if isinstance(node[0], tuple) else node[1:]
    return any(_iterator_body_reads_a_table_column(child) for child in children if isinstance(child, tuple))


def _iter_reference_nodes(node: Any) -> Iterable[tuple[Any, ...]]:
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "reference":
        yield node
        return
    # a call's argument list is a tuple of nodes, so its first element is a node, not a kind name
    children = node if isinstance(node[0], tuple) else node[1:]
    for child in children:
        if isinstance(child, tuple):
            yield from _iter_reference_nodes(child)


def _validate_relationship_modifier_filters(
    filter_arguments: tuple[tuple[Any, ...], ...],
) -> None:
    """Validate Boolean and supported date filters beside a relationship modifier."""
    for filter_argument in filter_arguments:
        if (
            filter_argument[0] == "call"
            and filter_argument[1] in _TIME_FILTER_FUNCTIONS
        ):
            _validate_literal_positions(filter_argument)
            continue
        predicate, _keep = _calculate_filter_argument(filter_argument)
        _calculate_boolean_filter_column(predicate)


def _is_divide_alternate_constant(node: tuple[Any, ...]) -> bool:
    """DIVIDE accepts a numeric literal, non-empty string, TRUE(), or BLANK() as its alternate result."""
    if node[0] in {"number", "blank"}:
        return True
    if node[0] == "string" and bool(node[1]):
        return True
    if node[0] == "boolean" and node[1] is True:
        return True
    return (
        node[0] == "unary"
        and node[1] in {"+", "-"}
        and node[2][0] == "number"
    )


# Scalar math verified against Power BI Desktop 2.157.879.0 (ADOMD, iteration 64).
# value is (minimum, maximum) argument count.
_SCALAR_MATH_ARITY = {
    "INT": (1, 1), "TRUNC": (1, 2), "SIGN": (1, 1), "SQRT": (1, 1),
    "EXP": (1, 1), "LN": (1, 1), "MOD": (2, 2), "POWER": (2, 2),
    "CEILING": (2, 2), "FLOOR": (2, 2),
}


def _round_to_multiple(
    function: str, number: Decimal | None, significance: Decimal | None
) -> Decimal | None:
    """CEILING/FLOOR to a multiple, following Power BI's sign and blank rules."""
    if number is None:
        return None
    if number == 0:
        return Decimal(0)
    if significance is None or significance == 0:
        if function == "CEILING":
            return Decimal(0)
        raise MeasureRuntimeError("FLOOR needs a significance other than zero.")
    if number > 0 and significance < 0:
        raise MeasureRuntimeError(
            f"{function} needs a significance with the same sign as the number."
        )
    rounding = ROUND_CEILING if function == "CEILING" else ROUND_FLOOR
    with localcontext() as exact:
        exact.prec = max(_EXACT_PRECISION, number.adjusted() + 30)  # keep every integer digit
        step = abs(significance)
        if significance < 0:  # both negative: round the magnitude, keep the sign
            return -(abs(number) / step).to_integral_value(rounding=rounding) * step
        return (number / step).to_integral_value(rounding=rounding) * step


def _scalar_math_value(function: str, values: list[Decimal | None]) -> Decimal | None:
    """Evaluate a scalar math function with Power BI's blank handling.

    A blank first argument returns blank for INT, TRUNC, SIGN, SQRT, MOD and POWER;
    EXP(BLANK()) is 1 and POWER(x, BLANK()) is 1 (blank counts as zero there).
    Arguments that make Power BI raise an error raise MeasureError instead.
    LN(BLANK()) is -Infinity in Power BI, so it is rejected locally.
    """
    first = values[0]
    if any(value is not None and not value.is_finite() for value in values):
        if function == "TRUNC" and first is not None and not first.is_finite() and all(value is None or value.is_finite() for value in values[1:]):
            return first  # TRUNC of Infinity is Infinity, an error value
        raise MeasureRuntimeError(
            f"An argument of function '{function}' has the wrong data type or the result is too large or too small."
        )
    if function in {"CEILING", "FLOOR"}:
        return _round_to_multiple(function, first, values[1])
    if function == "EXP":
        return (first or Decimal(0)).exp()
    if function == "LN":
        if first is None:
            return Decimal("-Infinity")
        if first <= 0:
            error = MeasureRuntimeError("LN needs a number greater than zero.")
            error.infinity = False
            raise error
        return first.ln()
    if function == "POWER":
        exponent = values[1] or Decimal(0)
        if first is None:
            if values[1] is None:
                raise MeasureRuntimeError("An argument of function 'POWER' has the wrong data type or the result is too large or too small.")
            return None
        if first == 0 and exponent <= 0:
            raise MeasureRuntimeError("POWER of zero needs a positive exponent.")
        if first < 0:
            if abs(exponent) >= 4294967295:  # Power BI refuses such exponents for a negative base
                raise MeasureRuntimeError(
                    "An argument of function 'POWER' has the wrong data type or the result is too large or too small."
                )
            if exponent != exponent.to_integral_value():
                # only an exact odd root (exponent 1/3, 1/5, -1/3 ...) has a real result: the negative of the root
                exponent_float = float(exponent)
                reciprocal = round(1 / exponent_float) if exponent_float else 0
                if not reciprocal % 2 or 1 / reciprocal != exponent_float:
                    raise MeasureRuntimeError(
                        "An argument of function 'POWER' has the wrong data type or the result is too large or too small."
                    )
                return -((-first) ** exponent)
        if abs(exponent) > 1000:  # Power BI computes POWER in double precision; huge exponents amplify the difference
            overflow = MeasureRuntimeError("POWER result is outside the supported numeric range.")
            try:
                if exponent == exponent.to_integral_value():
                    result, square, count = 1.0, float(first), int(abs(exponent))
                    while count:  # repeated squaring, as the engine does
                        if count & 1:
                            result *= square
                        square *= square
                        count >>= 1
                    if exponent < 0:
                        if not result:  # the reciprocal of an underflowed power is infinite
                            raise overflow
                        result = 1 / result if not math.isinf(result) else 0.0
                else:
                    result = math.pow(float(first), float(exponent))
            except (OverflowError, ValueError, ZeroDivisionError) as error:
                raise overflow from error
            if math.isinf(result) or math.isnan(result):
                raise overflow
            return Decimal(repr(result))
        return first ** exponent
    if function == "MOD":
        divisor = values[1] or Decimal(0)
        if first is None:
            return None
        if divisor == 0:
            raise MeasureRuntimeError("MOD cannot divide by zero.")
        with localcontext() as exact:
            exact.prec = _EXACT_PRECISION  # % needs the whole quotient to fit
            remainder = first % divisor  # sign follows the dividend
            if remainder != 0 and (remainder < 0) != (divisor < 0):
                remainder += divisor  # DAX: result takes the divisor's sign
        return remainder
    if first is None:
        return None
    if function == "INT":
        return first.to_integral_value(rounding=ROUND_FLOOR)
    if function == "SIGN":
        return Decimal((first > 0) - (first < 0))
    if function == "SQRT":
        if first < 0:
            raise MeasureRuntimeError("SQRT needs a number that is zero or greater.")
        return first.sqrt()
    # TRUNC(number[, digits])
    digits = values[1] if len(values) > 1 and values[1] is not None else Decimal(0)
    if digits.is_finite():
        digits = digits.to_integral_value(rounding=ROUND_HALF_UP)  # live Power BI (iteration 88): fractional digits round like ROUND's (1.9 is 2, 1.1 is 1)
    if not digits.is_finite():
        raise MeasureRuntimeError("TRUNC digits must be a number.")
    if digits > 28:
        return first  # live Power BI (iteration 88): nothing is left to cut (digits 29 and 100 give the number itself)
    if digits < -28:
        return Decimal(0)
    with localcontext() as exact:
        exact.prec = _EXACT_PRECISION  # quantize must hold every kept digit
        return first.quantize(Decimal(1).scaleb(-int(digits)), rounding=ROUND_DOWN)


# Power BI computes in IEEE doubles; larger magnitudes are errors there.
_DOUBLE_MAX = Decimal("1.7976931348623157E+308")
_EXACT_PRECISION = 100


def _scalar_math(function: str, values: list[Decimal | None]) -> Decimal | None:
    result = _scalar_math_value(function, values)
    if result is None:
        return None
    if not result.is_finite():
        return result  # an Infinity argument that the function passes through (TRUNC)
    if result == 0:
        return Decimal(0)  # no negative zero: Power BI shows 0
    if abs(result) > _DOUBLE_MAX:
        raise MeasureRuntimeError(f"{function} result is outside the supported numeric range.")
    return result


def _checked_double(result: Decimal) -> Decimal:
    """Power BI shows 0 for a negative zero and returns Infinity beyond the double range."""
    if not result.is_finite():
        return result
    if result == 0:
        return Decimal(0)
    if abs(result) > _DOUBLE_MAX:
        return Decimal("Infinity") if result > 0 else Decimal("-Infinity")
    return result


def _power(base: Decimal | None, exponent: Decimal | None) -> Decimal | None:
    """The ^ operator: POWER's rules, BLANK()^n is blank and n^BLANK() is 1."""
    return _scalar_math("POWER", [base, exponent])


def _binary_value(operator: str, left: Decimal | None, right: Decimal | None) -> Decimal | None:
    """+ - * / with Power BI's blank and IEEE rules (verified on 2.157.879.0).

    Blank counts as zero for + and - unless both sides are blank; * and / return
    blank when the left side is blank. x/0 and x/BLANK() are Infinity (NaN for 0/0),
    and results beyond the double range are Infinity.
    """
    quiet = dax_typed.QUIET
    if operator in {"+", "-"}:
        if left is None and right is None:
            return None
        left_value, right_value = left or Decimal(0), right or Decimal(0)
        return _checked_double(quiet.add(left_value, right_value) if operator == "+" else quiet.subtract(left_value, right_value))
    if left is None:
        return None
    if operator == "*":
        return None if right is None else _checked_double(quiet.multiply(left, right))
    divisor = Decimal(0) if right is None else right
    if divisor == 0:
        if left.is_nan() or left == 0:
            return Decimal("NaN")
        return Decimal("Infinity") if left > 0 else Decimal("-Infinity")
    return _checked_double(quiet.divide(left, divisor))


def _is_abs_of_blank(node: tuple[Any, ...]) -> bool:
    return (
        node[0] == "call"
        and node[1] == "ABS"
        and len(node[2]) == 1
        and node[2][0][0] == "blank"
    )


_GENERAL_CLEAR_FUNCTIONS = {"ALL", "ALLNOBLANKROW", "REMOVEFILTERS", "ALLEXCEPT", "ALLCROSSFILTERED"}
_GENERAL_BOOLEAN_CALLS = {"AND", "OR", "NOT", "ISBLANK", "CONTAINSSTRING", "CONTAINSSTRINGEXACT", "ISNUMBER", "ISTEXT", "CONTAINS"}


def _is_general_table_filter(node: Any) -> bool:
    """A CALCULATE filter argument that is a table expression (its columns' values become the filter)."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] in {"table_call", "tableconstructor", "table"}:
        return True
    if node[0] == "var":
        return True
    return node[0] == "call" and (
        node[1] in _TABLE_FUNCTION_ARITY or node[1] in dax_time_sets.SET_FUNCTIONS or node[1] in _NONBLANK_TABLES
        or node[1] in {"FILTER", "GENERATESERIES", "ROW"} or node[1] in _TIME_FILTER_FUNCTIONS
    )


def _general_calculate_filters_valid(filters: tuple[tuple[Any, ...], ...], legacy_sets_ok: bool = False) -> bool:
    """Whether every CALCULATE filter argument has a shape the general (any table or Boolean expression) path evaluates."""
    # date sets: the old ladder keeps a CALCULATE whose time functions all have its own shape; one other date set sends all of them here
    general_time_sets = legacy_sets_ok or any(_new_route_time_set(item) for item in filters)
    for node in filters:
        wrapped = False
        while isinstance(node, tuple) and node[:2] == ("call", "KEEPFILTERS") and len(node[2]) == 1:
            node = node[2][0]
            wrapped = True
        if not isinstance(node, tuple) or not node:
            return False
        if node[0] == "call" and node[1] in _GENERAL_CLEAR_FUNCTIONS:
            continue
        if node[0] == "call" and node[1] in dax_time_sets.SET_FUNCTIONS and (general_time_sets or wrapped or _new_route_time_set(node)):
            continue  # date sets are tables with the lineage of their column (iteration 84)
        if node[0] == "call" and node[1] in _TIME_FILTER_FUNCTIONS | {"USERELATIONSHIP", "CROSSFILTER", "ALLSELECTED"}:
            return False  # these keep their dedicated paths
        if _is_general_table_filter(node):
            continue
        if node[0] in {"comparison", "logical", "in", "unary", "reference"} or node[0] == "call":
            continue  # any expression over the columns of one table: it is checked when evaluated
        return False
    return True


_RELATIONSHIP_MODIFIERS = {"USERELATIONSHIP", "CROSSFILTER"}


def _time_filters_beside_general_filters(arguments: tuple[tuple[Any, ...], ...]) -> bool:
    """CALCULATE(e, <date sets>, <any Boolean / table / clearing filters>): live Power BI evaluates every filter in the outer context,
    so a date set may sit beside FILTER(ALL(T), ..), ALL(T) and column tests in any order."""
    filters = arguments[1:]
    return any(a[0] == "call" and a[1] in _TIME_FILTER_FUNCTIONS for a in filters) and _general_calculate_filters_valid(
        tuple(a for a in filters if not (a[0] == "call" and a[1] in _TIME_FILTER_FUNCTIONS | _RELATIONSHIP_MODIFIERS))
    )


_MIX_MODIFIERS = _RELATIONSHIP_MODIFIERS | {"ALLSELECTED"}


def _modifier_mix_filters_valid(filters: tuple[tuple[Any, ...], ...]) -> bool:
    """CALCULATE filters that mix USERELATIONSHIP / CROSSFILTER with clearing, Boolean and table filters (general path)."""
    modifiers = [
        node for node in filters if isinstance(node, tuple) and node[:1] == ("call",) and node[1] in _MIX_MODIFIERS
    ]
    if not modifiers:
        return False
    for node in modifiers:
        if node[1] == "USERELATIONSHIP":
            _validate_userelationship_call(node)
        elif node[1] == "CROSSFILTER":
            _validate_crossfilter_call(node)
        else:
            _validate_filter_clear_call(node, "ALLSELECTED")
    rest = tuple(node for node in filters if node not in modifiers)
    return not rest or _general_calculate_filters_valid(rest)


def _validate_general_filter_literals(node: tuple[Any, ...]) -> None:
    if node[:2] == ("call", "KEEPFILTERS") and len(node[2]) == 1:
        node = node[2][0]
    if node[0] in {"comparison", "logical", "in", "unary"}:
        _validate_literal_positions(node, allow_blank=True)


def _legacy_calculate_filters_valid(arguments: tuple[tuple[Any, ...], ...]) -> None:
    """The CALCULATE filter shapes the local engine has always supported; raises MeasureError for any other."""
    if any(_new_route_time_set(argument) or (
        isinstance(argument, tuple) and argument[:1] == ("call",) and argument[1] in dax_time_sets.SET_FUNCTIONS - _TIME_FILTER_FUNCTIONS
    ) for argument in arguments[1:]):
        raise MeasureError("This date set is evaluated by the general CALCULATE path.")
    contains_userelationship = any(
        _contains_function_call(argument, "USERELATIONSHIP")
        for argument in arguments[1:]
    )
    if contains_userelationship:
        modifiers = tuple(
            argument
            for argument in arguments[1:]
            if argument[0] == "call"
            and argument[1] == "USERELATIONSHIP"
        )
        filter_arguments = tuple(
            argument
            for argument in arguments[1:]
            if not (
                argument[0] == "call"
                and argument[1] == "USERELATIONSHIP"
            )
        )
        if not modifiers or any(
            _contains_function_call(argument, "USERELATIONSHIP")
            for argument in filter_arguments
        ):
            raise MeasureError(
                "USERELATIONSHIP must be a direct CALCULATE filter modifier in this local subset."
            )
        for modifier in modifiers:
            _validate_userelationship_call(modifier)
        _validate_relationship_modifier_filters(filter_arguments)
        return
    contains_crossfilter = any(
        _contains_function_call(argument, "CROSSFILTER")
        for argument in arguments[1:]
    )
    if contains_crossfilter:
        modifiers = tuple(
            argument
            for argument in arguments[1:]
            if argument[0] == "call"
            and argument[1] == "CROSSFILTER"
        )
        filter_arguments = tuple(
            argument
            for argument in arguments[1:]
            if not (
                argument[0] == "call"
                and argument[1] == "CROSSFILTER"
            )
        )
        if not modifiers or any(
            _contains_function_call(argument, "CROSSFILTER")
            for argument in filter_arguments
        ):
            raise MeasureError(
                "CROSSFILTER must be a direct CALCULATE filter modifier in this local subset."
            )
        for modifier in modifiers:
            _validate_crossfilter_call(modifier)
        _validate_relationship_modifier_filters(filter_arguments)
        return
    valid_filter_clear = (
        len(arguments) == 2
        and arguments[1][0] == "call"
        and arguments[1][1] in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "ALLCROSSFILTERED"}
    )
    contained_filter_clear = {
        function
        for function in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "ALLCROSSFILTERED"}
        if any(
            _contains_function_call(argument, function)
            for argument in arguments[1:]
        )
    }
    if contained_filter_clear:
        if _validate_mixed_filter_clear_calculate(arguments):
            return
        if not valid_filter_clear and _time_filters_beside_general_filters(arguments):
            return
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
        if _time_filters_beside_general_filters(arguments):
            return
        raise MeasureError(
            "A table-valued FILTER must be the only CALCULATE filter argument."
        )
    for filter_argument in arguments[1:]:
        if _new_route_time_set(filter_argument) or (filter_argument[0] == "call" and filter_argument[1] in dax_time_sets.SET_FUNCTIONS - _TIME_FILTER_FUNCTIONS):
            raise MeasureError("This date set is evaluated by the general CALCULATE path.")
        if filter_argument[0] == "call" and filter_argument[1] in _TIME_FILTER_FUNCTIONS:
            _validate_literal_positions(filter_argument)
        else:
            predicate, _keep = _calculate_filter_argument(filter_argument)
            _calculate_boolean_filter_column(predicate)
    return


def _validate_literal_positions(
    node: tuple[Any, ...], *, allow_blank: bool = False
) -> None:
    """Keep literals in time-intelligence syntax or validated CALCULATE filters."""
    kind = node[0]
    if kind in {"string", "var", "boolean"}:
        return
    if kind == "let":
        for _name, value in node[1]:
            if _is_held_table_value(value):
                continue  # a table held in a VAR; its arguments are checked when it is evaluated
            _validate_literal_positions(value, allow_blank=True)
        _validate_literal_positions(node[2], allow_blank=True)
        return
    if kind == "blank":
        if allow_blank:
            return
        raise MeasureError("BLANK() is supported only in explicitly allowed argument positions.")
    if kind == "blank_comment":
        return
    if kind == "omitted":
        raise MeasureError("Only TOTALYTD's optional filter argument can be omitted.")
    if kind == "call":
        function, arguments = node[1], node[2]
        if function == "DIVIDE":
            for operand in arguments[:2]:
                if operand[0] != "blank" and not _is_abs_of_blank(operand):
                    _validate_literal_positions(operand)
            if len(arguments) == 3:
                if not _is_divide_alternate_constant(arguments[2]):
                    raise MeasureError(
                        "DIVIDE alternate result must be a constant numeric value or BLANK()."
                    )
                if arguments[2][0] not in {"blank", "string", "boolean"}:
                    _validate_literal_positions(arguments[2])
            return
        if function in _SCALAR_MATH_ARITY:
            for argument in arguments:
                _validate_literal_positions(argument, allow_blank=True)
            return
        if function == "CALCULATETABLE":
            _validate_literal_positions(("call", "CALCULATE", ((("number", Decimal(0))),) + tuple(arguments[1:])))
            return
        if function in _TABLE_FUNCTION_ARITY or function in _RANK_ARITY:
            for index, argument in enumerate(arguments):
                if argument[0] in {"table", "omitted"} or (
                    _table_position(function, index) and _is_all_table_value_argument(argument)
                ):
                    continue  # a table expression, an omitted argument or an ASC/DESC/SKIP/DENSE keyword
                _validate_literal_positions(argument, allow_blank=True)
            return
        if (function in dax_time_sets.SET_FUNCTIONS and not (function in _TIME_FILTER_FUNCTIONS and _legacy_time_shape(node))) or function in _NONBLANK_TABLES or function in {"FIRSTNONBLANKVALUE", "LASTNONBLANKVALUE"}:
            for index, argument in enumerate(arguments):
                if index == 0 and _is_all_table_value_argument(argument):
                    continue  # a column or table expression of dates
                _validate_literal_positions(argument, allow_blank=True)
            return
        if function in {"CONCATENATEX", "XNPV"}:
            for argument in arguments[1:]:
                if argument[0] != "table":  # ASC / DESC
                    _validate_literal_positions(argument, allow_blank=True)
            return
        if function in {"IF", "IF.EAGER", "ISBLANK", "IFERROR", "SWITCH", "ABS", "AND", "OR", "NOT", "SELECTEDVALUE", "ERROR", "CUSTOMDATA", "EVALUATEANDLOG"} or function in _TYPED_ARITY or function in _LOOKUP_ARITY or (
            function in {"MIN", "MAX"} and len(arguments) == 2
        ):
            for index, argument in enumerate(arguments):
                if function in {"ISEMPTY", "CONTAINS", "CONTAINSROW"} and index == 0 and _is_all_table_value_argument(argument):
                    continue  # a table expression, checked where it is evaluated
                _validate_literal_positions(argument, allow_blank=True)
            return
        if function in {"NAMEOF", "TABLEOF"}:
            return
        if function == "COALESCE":
            for argument in arguments:
                if _is_coalesce_table_argument(argument):
                    raise MeasureError(
                        "COALESCE needs scalar expressions; table-valued arguments are not supported."
                    )
                _validate_literal_positions(argument, allow_blank=True)
            return
        if function == "CALCULATE":
            if not arguments:
                raise MeasureError("CALCULATE needs an expression.")
            _validate_literal_positions(arguments[0], allow_blank=allow_blank)
            try:
                _legacy_calculate_filters_valid(arguments)
            except MeasureError:
                if not _general_calculate_filters_valid(arguments[1:]) and not _modifier_mix_filters_valid(arguments[1:]):
                    raise
                for filter_argument in arguments[1:]:
                    _validate_general_filter_literals(filter_argument)
            return
        if function in {"MAXX", "MINX"}:
            _validate_literal_positions(arguments[1], allow_blank=True)
            return
        if function in {"SUMX", "AVERAGEX"} or function in dax_math.STAT_ITERATORS:
            _validate_literal_positions(arguments[1])
            for extra in arguments[2:]:
                _validate_literal_positions(extra)
            return
        if function in {"COUNTX", "COUNTAX"}:
            _validate_count_iterator_literals(arguments[1])
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
        if function in {"REMOVEFILTERS", "ALLCROSSFILTERED"}:
            raise MeasureError(
                f"{function} is supported only as a CALCULATE filter modifier."
            )
        if function in {"ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED"}:
            raise MeasureError(
                f"{function} is supported only as a CALCULATE filter modifier or "
                "a COUNTROWS/SUMX/AVERAGEX/MAXX/MINX/COUNTX/COUNTAX table expression in this local subset."
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
                # ABS(BLANK()) is blank in Power BI; ROUND(BLANK(), 0) and other calls are not modelled for blanks.
                _validate_literal_positions(argument, allow_blank=allow_blank and function == "ABS")
        return
    if kind == "in":
        _validate_literal_positions(node[1], allow_blank=True)
        if not _is_all_table_value_argument(node[2]):
            _validate_literal_positions(node[2], allow_blank=True)
        return
    operand_blank = allow_blank or kind in {"unary", "binary", "comparison", "logical", "concat", "in", "tableconstructor", "tuple", "strict_equal"}
    for child in node[1:]:
        if isinstance(child, tuple) and child:
            _validate_literal_positions(child, allow_blank=operand_blank)


def _validate_count_iterator_literals(node: tuple[Any, ...]) -> None:
    """Allow bounded text conditions and string/blank results in COUNTX/COUNTAX."""
    if node[0] in {"string", "blank"}:
        return
    if node[0] == "call" and node[1] == "IF" and len(node[2]) == 3:
        _validate_count_iterator_condition(node[2][0])
        _validate_count_iterator_literals(node[2][1])
        _validate_count_iterator_literals(node[2][2])
        return
    _validate_literal_positions(node)


def _validate_count_iterator_condition(node: tuple[Any, ...]) -> None:
    """Accept the local numeric conditions plus text-column equality checks."""
    kind = node[0]
    if kind == "comparison":
        operator, left, right = node[1:4]  # a 5th item marks an IN comparison
        text_equality = (
            operator in {"=", "<>"}
            and (
                (left[0] == "reference" and right[0] == "string")
                or (right[0] == "reference" and left[0] == "string")
            )
        )
        if text_equality:
            return
        _validate_literal_positions(node)
        return
    if kind == "logical":
        _validate_count_iterator_condition(node[2])
        _validate_count_iterator_condition(node[3])
        return
    if kind == "call" and node[1] in {"AND", "OR"}:
        for argument in node[2]:
            _validate_count_iterator_condition(argument)
        return
    if kind == "call" and node[1] == "NOT":
        _validate_count_iterator_condition(node[2][0])
        return
    _validate_literal_positions(node)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.variables: list[str] = []
        self._in_var_binding: bool = False

    def parse(self) -> tuple[Any, ...]:
        if not self.tokens:
            raise MeasureError("Enter a DAX expression.")
        node = self._expression()
        if self.index != len(self.tokens):
            raise MeasureError(f"Unexpected token {self.tokens[self.index].value!r}.")
        node = _rewrite_total_td(node)
        _validate_literal_positions(node)
        return node

    def _expression(self) -> tuple[Any, ...]:
        if self._is_keyword("VAR"):
            return self._variables()
        return self._logical_or()

    def _is_keyword(self, word: str) -> bool:
        return (
            self.index < len(self.tokens)
            and self.tokens[self.index].kind == "identifier"
            and self.tokens[self.index].value == word
        )

    def _variables(self) -> tuple[Any, ...]:
        """VAR name = expression ... RETURN expression."""
        declared = len(self.variables)
        bindings: list[tuple[str, tuple[Any, ...]]] = []
        block_names: set[str] = set()
        while self._is_keyword("VAR"):
            self._take()
            name = self._take()
            if name.kind != "identifier" or name.value in _FUNCTIONS or name.value in {"VAR", "RETURN", "TRUE", "FALSE", "BLANK"}:
                raise MeasureError(f"{name.value!r} is not a valid variable name.")
            if name.value in block_names:
                raise MeasureError(
                    f"Variable {name.value.lower()!r} cannot be created because a variable with the same name already exists."
                )
            block_names.add(name.value)
            self._expect("=")
            self._in_var_binding = True
            try:
                value = self._logical_or()
            finally:
                self._in_var_binding = False
            bindings.append((name.value, value))
            self.variables.append(name.value)
        if not self._is_keyword("RETURN"):
            raise MeasureError("A VAR block needs a RETURN expression.")
        self._take()
        body = self._expression()
        del self.variables[declared:]
        return ("let", tuple(bindings), body)

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

    _AFTER_NOT_GROUP = {"=", "<>", "<", "<=", ">", ">=", "&", "+", "-", "*", "/", "^"}

    def _not_is_operator(self) -> bool:
        """NOT in front of an operand rather than NOT( ... ) as a function: a bare NOT, or NOT (x) followed by an operator."""
        if not self._is_keyword("NOT"):
            return False
        if self.index + 1 >= len(self.tokens) or self.tokens[self.index + 1].kind != "(":
            return True
        depth, position = 0, self.index + 1
        while position < len(self.tokens):
            depth += {"(": 1, ")": -1}.get(self.tokens[position].kind, 0)
            if depth == 0:
                after = self.tokens[position + 1] if position + 1 < len(self.tokens) else None
                return after is not None and (after.kind in self._AFTER_NOT_GROUP or (after.kind == "identifier" and after.value == "IN"))
            position += 1
        return False

    def _comparison(self) -> tuple[Any, ...]:
        node = self._concatenation()
        if self._is_keyword("IN"):
            self._take()
            members = self._concatenation()
            if members == ("tableconstructor", ()):
                # {} alone is an empty table, but Power BI rejects it as the right side of IN
                raise MeasureError("IN needs a table or at least one value; an empty table constructor {} is not accepted.")
            return _membership(node, members)
        if self._peek() in {"=", "==", "<>", "<", "<=", ">", ">="}:
            while self._peek() in {"=", "==", "<>", "<", "<=", ">", ">="}:  # a < b < c reads (a < b) < c
                operator = self._take().kind
                right = self._concatenation()
                node = ("strict_equal", node, right) if operator == "==" else ("comparison", operator, node, right)
        return node

    def _concatenation(self) -> tuple[Any, ...]:
        node = self._arithmetic()
        while self._peek() == "&":
            self._take()
            node = ("concat", node, self._arithmetic())
        return node

    def _arithmetic(self) -> tuple[Any, ...]:
        node = self._term()
        while self._peek() in {"+", "-"}:
            operator = self._take().kind
            right = self._variables() if self._is_keyword("VAR") else self._term()
            node = ("binary", operator, node, right)
        return node

    def _term(self) -> tuple[Any, ...]:
        node = self._unary()
        while self._peek() in {"*", "/"}:
            operator = self._take().kind
            right = self._variables() if self._is_keyword("VAR") else self._unary()
            node = ("binary", operator, node, right)
        return node

    def _unary(self) -> tuple[Any, ...]:
        if self._not_is_operator():
            # NOT negates the whole comparison that follows: NOT 2>1 && 1>2 reads (NOT (2>1)) && (1>2); NOT (1>2) > (2>1) reads
            # NOT ((1>2) > (2>1)); 1 + NOT 1>2 is 2 (Power BI, tools/dax_battery_not_operator.json)
            self._take()
            operand = self._comparison()
            if self._is_keyword("IN"):  # Power BI folds a chained IN into the operand and rejects some of those; not modelled
                raise MeasureError("NOT followed by a comparison and IN needs parentheses in the local engine.")
            return ("call", "NOT", (operand,))
        if self._peek() in {"+", "-"}:
            operator = self._take().kind
            return ("unary", operator, self._unary())
        return self._power()

    def _power(self) -> tuple[Any, ...]:
        base = self._primary()
        if self._peek() == "^":  # binds tighter than a leading minus and groups to the right
            self._take()
            return ("binary", "^", base, self._unary())
        return base

    def _primary(self) -> tuple[Any, ...]:
        token = self._take()
        if token.kind == "number":
            try:
                value = Decimal(token.value)
                digits = token.value.lower().split("e")[0].replace(".", "").lstrip("0")
                if len(digits) > 15 and ("." in token.value or "e" in token.value.lower() or abs(value) > 9223372036854775807):
                    value = Decimal(repr(float(token.value)))  # Power BI reads such literals as doubles
            except (DecimalException, OverflowError) as exc:
                raise MeasureError(f"Invalid numeric literal {token.value!r}.") from exc
            if not value.is_finite():
                raise MeasureError("Numeric literals must be finite.")
            return ("number", value)
        if token.kind == "string":
            return ("string", token.value)
        if token.kind == "(":
            node = self._expression()
            if self._peek() == ",":  # (a, b, ...) is a row of values, used inside {...} and with IN
                members = [node]
                while self._peek() == ",":
                    self._take()
                    members.append(self._expression())
                self._expect(")")
                return ("tuple", tuple(members))
            self._expect(")")
            return node
        if token.kind == "{" and self._peek() == "}":
            self._take()
            return ("tableconstructor", ())
        if token.kind == "{":
            items: list[tuple[Any, ...]] = []
            while True:
                items.append(self._expression())
                if self._peek() != ",":
                    break
                self._take()
            self._expect("}")
            widths = {len(item[1]) if item[0] in {"tuple", "tableconstructor"} else 0 for item in items}
            if len(widths) > 1:
                raise MeasureError("All rows of a table constructor must have the same number of values.")
            return ("tableconstructor", tuple(items))
        if token.kind == "reference":
            table, column = token.value.split("\0", 1)
            return ("reference", table, column)
        if token.kind == "blank_comment":
            return ("blank_comment",)
        if token.kind == "table":
            return ("table", token.value)
        if token.kind == "identifier":
            function = token.value
            if function in self.variables and self._peek() != "(":
                return ("var", function)
            if function in {"TRUE", "FALSE"}:
                if self._peek() == "(":
                    self._take()
                    self._expect(")")
                return ("boolean", function == "TRUE")
            if function == "BLANK":
                self._expect("(")
                self._expect(")")
                return ("blank",)
            if function in {"DISTINCT", "VALUES"} and self._peek() == "(":
                self._take()
                argument = self._expression()
                self._expect(")")
                if argument[0] not in {"reference", "table", "call", "table_call", "tableconstructor"}:
                    raise MeasureError(f"{function} needs one source column reference or table.")
                return ("table_call", function, argument)
            if function not in _FUNCTIONS:
                if self._peek() in {",", ")"} or (self._in_var_binding and (self._is_keyword("RETURN") or self._is_keyword("VAR"))):
                    return ("table", function)
                raise MeasureError(f"Function {function} is not supported by the local DAX engine.")
            if self._peek() in {",", ")"}:
                return ("table", function)  # a keyword such as MONTH in DATEDIFF(...) or INTEGER in CONVERT(...)
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
            if function in dax_math.STAT_PERCENTILE_COLUMN and len(arguments) == 2 and arguments[1][0] == "blank":
                arguments[1] = ("number", Decimal(0))  # live Power BI (iteration 88): a BLANK() percentile is 0 (PERCENTILE.EXC of 0 is an error)
            if function in {"PERCENTILEX.INC", "PERCENTILEX.EXC"} and len(arguments) == 3 and arguments[2][0] == "blank":
                arguments[2] = ("number", Decimal(0))
            if function == "RELATEDTABLE":  # CALCULATETABLE(table): the row context of the enclosing iterator becomes the filter
                if len(arguments) != 1 or arguments[0][0] != "table":
                    raise MeasureError("RELATEDTABLE needs one table, such as RELATEDTABLE('Sales').")
                return ("call", "CALCULATETABLE", (arguments[0],))
            if function in dax_time_sets.BALANCES:
                return _balance_call(function, arguments)
            if function in _ROW_ORDER_FUNCTIONS and any(_contains_function_call(argument, "TABLEOF") for argument in arguments):
                # live Power BI (iteration 92): TABLEOF hands the rows over in the engine's own order, not the table's (CONCATENATEX gave East,East,East,West,West,North for a table stored East,West,East,North,West,East)
                raise MeasureError(f"{function} over TABLEOF depends on the row order, which is not modelled in the local engine.")
            if function in dax_time_sets.SET_FUNCTIONS and _time_set_call_is_new_form(function, arguments):
                _validate_time_set_call(function, arguments)
            elif function in dax_math.STAT_PERCENTILE_COLUMN:
                if len(arguments) != 2 or arguments[0][0] != "reference":
                    raise MeasureError(f"{function} needs a column reference and a percentile between 0 and 1.")
            elif function in {
                "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA",
                "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "MEDIAN", "PRODUCT", "COUNTBLANK",
            } | dax_math.STAT_COLUMN_FUNCTIONS:
                if function in {"MIN", "MAX"} and len(arguments) == 2 and all(a[0] != "omitted" for a in arguments):
                    pass  # MAX(a, b) / MIN(a, b): the scalar form
                elif len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(f"{function} needs one column reference, such as {function}([Amount]).")
            elif function == "COUNTROWS" and (
                len(arguments) > 1
                or (arguments and not _is_all_table_value_argument(arguments[0]))
            ):
                if arguments and arguments[0][0] == "call" and arguments[0][1] == "ALLCROSSFILTERED":
                    raise MeasureError("ALLCROSSFILTERED function cannot be used as a table expression. It can appear only as a filter in CALCULATE.")
                raise MeasureError(
                    "COUNTROWS needs no argument or one loaded table/ALL table expression."
                )
            elif function == "DIVIDE" and len(arguments) not in {2, 3}:
                raise MeasureError("DIVIDE needs a numerator, denominator, and optional alternate result.")
            elif function == "COALESCE" and (
                len(arguments) < 2
                or any(argument[0] == "omitted" for argument in arguments)
            ):
                raise MeasureError(
                    "COALESCE needs at least two non-omitted scalar expressions."
                )
            elif function == "COALESCE" and any(
                _is_coalesce_table_argument(argument) for argument in arguments
            ):
                raise MeasureError(
                    "COALESCE needs scalar expressions; table-valued arguments are not supported."
                )
            elif function == "ABS" and len(arguments) != 1:
                raise MeasureError("ABS needs one numeric expression.")
            elif function == "CONCATENATEX" and (
                len(arguments) < 2 or not _is_all_table_value_argument(arguments[0])
            ):
                raise MeasureError(
                    "CONCATENATEX needs a table, an expression, and optional delimiter and order arguments."
                )
            elif function == "XNPV":
                if len(arguments) < 4:
                    raise MeasureError("Too few arguments were passed to the XNPV function. The minimum argument count for the function is 4.")
                if len(arguments) > 4:
                    raise MeasureError("Too many arguments were passed to the XNPV function. The maximum argument count for the function is 4.")
                if not _is_all_table_value_argument(arguments[0]):
                    raise MeasureError("The XNPV function expects a table expression for argument '1', but a string or numeric expression was used.")
                if any(argument[0] == "omitted" for argument in arguments):
                    raise MeasureError("The XNPV function does not accept omitted arguments.")
            elif function == "IF.EAGER":
                if len(arguments) < 2:
                    raise MeasureError("Too few arguments were passed to the IF.EAGER function. The minimum argument count for the function is 2.")
                if len(arguments) > 3:
                    raise MeasureError("Too many arguments were passed to the IF.EAGER function. The maximum argument count for the function is 3.")
                if any(_is_all_table_value_argument(arg) or _is_coalesce_table_argument(arg) for arg in arguments[1:]):
                    raise MeasureError("The expression refers to multiple columns. Multiple columns cannot be converted to a scalar value.")
            elif function == "ERROR":
                if len(arguments) < 1:
                    raise MeasureError("Too few arguments were passed to the ERROR function. The minimum argument count for the function is 1.")
                if len(arguments) > 1:
                    raise MeasureError("Too many arguments were passed to the ERROR function. The maximum argument count for the function is 1.")
                if arguments[0][0] != "string":
                    raise MeasureError("The function 'ERROR' expects its argument number 1 to be constant.")
            elif function == "CUSTOMDATA":
                if len(arguments) > 0:
                    raise MeasureError("Too many arguments were passed to the CUSTOMDATA function. The maximum argument count for the function is 0.")
            elif function == "NAMEOF":
                if len(arguments) < 1:
                    raise MeasureError("Too few arguments were passed to the NAMEOF function. The minimum argument count for the function is 1.")
                if len(arguments) > 1:
                    raise MeasureError("Valid arguments for component are TABLE, COLUMN, MEASURE, CALENDAR, FULL, SELF, and PARENT.")
                arg = arguments[0]
                if arg[0] not in {"reference", "table"} or (arg[0] == "reference" and not arg[1]):
                    raise MeasureError("Only measure or fully-qualified column or table or calendar references are allowed in NAMEOF function.")
            elif function == "TABLEOF":
                if len(arguments) < 1:
                    raise MeasureError("Too few arguments were passed to the TABLEOF function. The minimum argument count for the function is 1.")
                if len(arguments) > 1:
                    raise MeasureError("Too many arguments were passed to the TABLEOF function. The maximum argument count for the function is 1.")
                arg = arguments[0]
                if arg[0] != "reference" or not arg[1]:
                    raise MeasureError("The TABLEOF function only accepts a column reference, measure reference, or calendar reference as the argument number 1.")
            elif function == "EVALUATEANDLOG":
                if len(arguments) < 1:
                    raise MeasureError("Too few arguments were passed to the EVALUATEANDLOG function. The minimum argument count for the function is 1.")
                if len(arguments) > 3:
                    raise MeasureError("Too many arguments were passed to the EVALUATEANDLOG function. The maximum argument count for the function is 3.")
            elif function == "ALLCROSSFILTERED":
                if len(arguments) != 1:
                    raise MeasureError("ALLCROSSFILTERED needs one table expression.")
                if arguments[0][0] == "reference":
                    raise MeasureError(
                        f"A single value for column '{arguments[0][2]}' in table '{arguments[0][1]}' cannot be determined. "
                        "This can happen when a measure or function formula refers to a column that contains many values "
                        "without specifying an aggregation such as min, max, count, or sum to get a single result."
                    )
                if arguments[0][0] != "table":
                    raise MeasureError("ALLCROSSFILTERED needs one table expression.")
            elif function in {"ISONORAFTER", "ISAFTER"}:
                if len(arguments) < 2:
                    raise MeasureError(f"Too few arguments were passed to the {function} function. The minimum argument count for the function is 2.")
                if len(arguments) % 3 == 1:
                    raise MeasureError("IsOnOrAfter() function contains a scalar expression to compare without a value to compare against.")
            elif function in _TABLE_FUNCTION_ARITY and not (
                _TABLE_FUNCTION_ARITY[function][0] <= len(arguments)
                and (_TABLE_FUNCTION_ARITY[function][1] is None or len(arguments) <= _TABLE_FUNCTION_ARITY[function][1])
                and (function in {"INDEX", "OFFSET", "WINDOW"} or all(argument[0] != "omitted" for argument in arguments))
            ):
                raise MeasureError(f"{function} has the wrong number of arguments.")
            elif function == "ADDCOLUMNS" and len(arguments) % 2 == 0:
                raise MeasureError(f"{function} needs a table followed by pairs of a column name and an expression.")
            elif function in _RANK_ARITY and not (
                _RANK_ARITY[function][0] <= len(arguments) <= _RANK_ARITY[function][1]
            ):
                raise MeasureError(f"{function} has the wrong number of arguments.")
            elif function in _LOOKUP_ARITY and not (
                _LOOKUP_ARITY[function][0] <= len(arguments)
                and (_LOOKUP_ARITY[function][1] is None or len(arguments) <= _LOOKUP_ARITY[function][1])
                and all(argument[0] != "omitted" for argument in arguments)
            ):
                raise MeasureError(f"{function} has the wrong number of arguments.")
            elif function in {"FIRSTNONBLANK", "LASTNONBLANK", "FIRSTNONBLANKVALUE", "LASTNONBLANKVALUE"} and arguments[0][0] in {
                "number", "string", "boolean", "blank", "unary", "binary",
            }:
                raise MeasureError(f"{function} needs a column reference and an expression.")
            elif function == "ROW" and len(arguments) % 2:
                raise MeasureError("ROW needs pairs of a column name and an expression.")
            elif function in _COLUMN_SCALAR_ARITY and not (
                _COLUMN_SCALAR_ARITY[function][0] <= len(arguments) <= _COLUMN_SCALAR_ARITY[function][1]
                and arguments[0][0] == "reference"
            ):
                raise MeasureError(f"{function} needs a column reference{' and an optional alternate result' if function == 'SELECTEDVALUE' else ''}.")
            elif function in _TYPED_ARITY and not (
                _TYPED_ARITY[function][0] <= len(arguments) <= _TYPED_ARITY[function][1]
                and all(argument[0] != "omitted" for argument in arguments)
            ):
                low, high = _TYPED_ARITY[function]
                raise MeasureError(f"{function} needs {low if low == high else f'{low} to {high}'} argument(s).")
            elif function in _SCALAR_MATH_ARITY and not (
                _SCALAR_MATH_ARITY[function][0]
                <= len(arguments)
                <= _SCALAR_MATH_ARITY[function][1]
            ):
                low, high = _SCALAR_MATH_ARITY[function]
                raise MeasureError(
                    f"{function} needs {low if low == high else f'{low} or {high}'} numeric argument(s)."
                )
            elif function == "ROUND" and len(arguments) != 2:
                raise MeasureError("ROUND needs a numeric expression and a number of digits.")
            elif function in {"IF", "SWITCH"} and len(arguments) >= 2 and _mixes_table_and_scalar_branches(function, arguments):
                raise MeasureError(f"{function} cannot return a table in one branch and a single value in another.")
            elif function == "IF" and len(arguments) not in {2, 3}:
                raise MeasureError(
                    "IF needs a condition, a value for true, and an optional value for false."
                )
            elif function == "ISBLANK" and len(arguments) != 1:
                raise MeasureError("ISBLANK needs one argument.")
            elif function == "IFERROR" and len(arguments) != 2:
                raise MeasureError("IFERROR needs a value and a value to use if it is an error.")
            elif function == "SWITCH" and len(arguments) < 3:
                raise MeasureError(
                    "SWITCH needs an expression and at least one value/result pair."
                )
            elif function in {"AND", "OR"} and len(arguments) != 2:
                raise MeasureError(f"{function} needs two logical expressions.")
            elif function == "NOT" and len(arguments) != 1:
                raise MeasureError("NOT needs one logical expression.")
            elif function == "KEEPFILTERS" and len(arguments) != 1:
                raise MeasureError("KEEPFILTERS needs one filter expression.")
            elif function in _ALL_ITERATORS and (
                len(arguments) != (3 if function.startswith("PERCENTILEX") else 2)
                or not _is_all_table_value_argument(arguments[0])
            ):
                raise MeasureError(
                    f"{function} needs a loaded table or ALL table expression and one scalar expression."
                )
            elif function == "RELATED" and (
                len(arguments) != 1
                or arguments[0][0] != "reference"
                or not arguments[0][1]
            ):
                raise MeasureError(
                    "RELATED needs one fully qualified column reference, such as RELATED('Products'[Unit Price])."
                )
            elif function in {"TOTALYTD", "TOTALQTD", "TOTALMTD"}:
                if any(argument[0] == "omitted" for argument in arguments):
                    # live Power BI: an empty argument is an error, TOTALYTD(e, d, , "6/30") included
                    omitted_at = next(index for index, argument in enumerate(arguments) if argument[0] == "omitted") + 1
                    raise MeasureError(f"Argument '{omitted_at}' in {function} function is required.")
                year_end = None
                rest = list(arguments[2:])
                if function == "TOTALYTD" and len(rest) in {1, 2} and rest[-1][0] == "string":
                    year_end = rest.pop()
                if (
                    len(arguments) < 2 or arguments[1][0] != "reference" or len(rest) > 1
                    or (rest and rest[0][0] == "string") or (function != "TOTALYTD" and len(arguments) > 3)
                ):
                    raise MeasureError(
                        f"{function} needs an expression, a date column reference and an optional filter"
                        + (' and a "M/D" year end.' if function == "TOTALYTD" else ".")
                    )
                if year_end is not None:
                    _parse_year_end_date(year_end[1])
                if rest and not _general_calculate_filters_valid((rest[0],)):
                    raise MeasureError(f"{function} needs an expression and marked date-column reference. Filter expressions are not supported unless they are Boolean or table filters.")
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
                    and arguments[1][0] not in {"table", "omitted", "boolean"}
                    and arguments[2][0] not in {"table", "omitted", "boolean"}
                )
                if not valid_arguments:
                    raise MeasureError(
                        'DATESBETWEEN needs a marked date-column reference and date, ISO '
                        'date text or BLANK() start/end bounds.'
                    )
            elif function == "DATESINPERIOD":
                valid_interval = (
                    len(arguments) == 4
                    and arguments[0][0] == "reference"
                    and arguments[1][0] not in {"table", "omitted", "boolean"}
                    and arguments[2][0] not in {"table", "omitted", "boolean", "string"}
                    and arguments[3][0] == "table"
                    and str(arguments[3][1]).upper()
                    in {"DAY", "MONTH", "QUARTER", "YEAR"}
                )
                if not valid_interval:
                    raise MeasureError(
                        "DATESINPERIOD needs a marked date-column reference, a start date, "
                        "an interval count, and DAY, MONTH, QUARTER, or YEAR."
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
            elif function in {"PREVIOUSYEAR", "NEXTYEAR"}:
                valid_arguments = (
                    len(arguments) == 1 and arguments[0][0] == "reference"
                ) or (
                    len(arguments) == 2
                    and arguments[0][0] == "reference"
                    and arguments[1][0] == "string"
                )
                if not valid_arguments:
                    raise MeasureError(
                        f"{function} needs a marked date-column reference and an "
                        "optional M/D year-end string."
                    )
                if len(arguments) == 2:
                    _parse_year_end_date(arguments[1][1])
            elif function in {"PREVIOUSQUARTER", "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY"}:
                if len(arguments) != 1 or arguments[0][0] != "reference":
                    raise MeasureError(
                        f"{function} needs one marked date-column reference."
                    )
            elif function == "PARALLELPERIOD":
                valid_interval = (
                    len(arguments) == 3
                    and arguments[0][0] == "reference"
                    and arguments[2][0] == "table"
                    and str(arguments[2][1]).upper() in {"YEAR", "QUARTER", "MONTH"}
                )
                if not valid_interval or arguments[1][0] in {"table", "string", "omitted"}:
                    raise MeasureError(
                        "PARALLELPERIOD needs a date-column reference, numeric interval count, "
                        "and YEAR, QUARTER, or MONTH interval."
                    )
            elif function == "FILTER":
                try:
                    _validate_table_filter_call(
                        ("call", function, tuple(arguments)), allow_all_base=True
                    )
                except MeasureError:
                    # any table expression and any row predicate is valid DAX; it is evaluated row by row
                    if len(arguments) != 2 or not _is_all_table_value_argument(arguments[0]):
                        raise
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
                try:
                    contains_userelationship = any(
                        _contains_function_call(argument, "USERELATIONSHIP")
                        for argument in arguments[1:]
                    )
                    if contains_userelationship:
                        modifiers = tuple(
                            argument
                            for argument in arguments[1:]
                            if argument[0] == "call"
                            and argument[1] == "USERELATIONSHIP"
                        )
                        filter_arguments = tuple(
                            argument
                            for argument in arguments[1:]
                            if not (
                                argument[0] == "call"
                                and argument[1] == "USERELATIONSHIP"
                            )
                        )
                        if not modifiers or any(
                            _contains_function_call(argument, "USERELATIONSHIP")
                            for argument in filter_arguments
                        ):
                            raise MeasureError(
                                "USERELATIONSHIP must be a direct CALCULATE filter modifier in this local subset."
                            )
                        for modifier in modifiers:
                            _validate_userelationship_call(modifier)
                        _validate_relationship_modifier_filters(filter_arguments)
                        return ("call", function, tuple(arguments))
                    contains_crossfilter = any(
                        _contains_function_call(argument, "CROSSFILTER")
                        for argument in arguments[1:]
                    )
                    if contains_crossfilter:
                        modifiers = tuple(
                            argument
                            for argument in arguments[1:]
                            if argument[0] == "call"
                            and argument[1] == "CROSSFILTER"
                        )
                        filter_arguments = tuple(
                            argument
                            for argument in arguments[1:]
                            if not (
                                argument[0] == "call"
                                and argument[1] == "CROSSFILTER"
                            )
                        )
                        if not modifiers or any(
                            _contains_function_call(argument, "CROSSFILTER")
                            for argument in filter_arguments
                        ):
                            raise MeasureError(
                                "CROSSFILTER must be a direct CALCULATE filter modifier in this local subset."
                            )
                        for modifier in modifiers:
                            _validate_crossfilter_call(modifier)
                        _validate_relationship_modifier_filters(filter_arguments)
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
                    valid_allcrossfiltered = (
                        len(arguments) == 2
                        and arguments[1][0] == "call"
                        and arguments[1][1] == "ALLCROSSFILTERED"
                    )
                    contains_filter_clear = {
                        clear_function
                        for clear_function in {
                            "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "ALLCROSSFILTERED"
                        }
                        if any(
                            _contains_function_call(argument, clear_function)
                            for argument in arguments[1:]
                        )
                    }
                    if contains_filter_clear and _validate_mixed_filter_clear_calculate(
                        tuple(arguments)
                    ):
                        return ("call", function, tuple(arguments))
                    if contains_filter_clear and not (
                        valid_removefilters or valid_all or valid_allnoblankrow or valid_allexcept or valid_allselected or valid_allcrossfiltered
                    ):
                        clear_function = sorted(contains_filter_clear)[0]
                        raise MeasureError(
                            f"{clear_function} must be the only CALCULATE filter argument in this local subset."
                        )
                    if valid_removefilters or valid_all or valid_allnoblankrow or valid_allexcept or valid_allselected or valid_allcrossfiltered:
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
                except MeasureError:
                    if not _general_calculate_filters_valid(tuple(arguments[1:])) and not _modifier_mix_filters_valid(tuple(arguments[1:])) and not _time_filters_beside_general_filters(tuple(arguments)):
                        raise
            if (function in _ALL_ITERATORS or function in {"CONCATENATEX", "XNPV"} or function == "FILTER") and len(arguments) >= 2:
                _check_set_iterator_body(arguments[0], arguments[1])  # live Power BI: FILTER(date set, ..) reads only the set's own column too
                if function == "XNPV" and len(arguments) >= 3:
                    _check_set_iterator_body(arguments[0], arguments[2])
            if function in {"UNION", "EXCEPT", "INTERSECT", "CROSSJOIN"} and any(argument[0] == "reference" for argument in arguments):
                # live Power BI (iteration 84, critic): a bare column where a table is expected is a compile-time error
                # ("A single value for column .. cannot be determined"), also in a branch that is never run
                raise MeasureError(f"{function} needs table expressions; a column reference has no single value.")
            if function == "FILTER" and len(arguments) == 2:
                _check_single_column_filter(arguments[0], arguments[1])
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


_TOTAL_TO_DATES = {"TOTALYTD": "DATESYTD", "TOTALQTD": "DATESQTD", "TOTALMTD": "DATESMTD"}


def _rewrite_total_td(node: Any, filter_position: bool = False) -> Any:
    """TOTALYTD(e, d [, filter] [, year_end]) is CALCULATE(e, DATESYTD(d [, year_end]) [, filter]) (live Power BI, 567 of 567
    pairs); TOTALQTD / TOTALMTD take no year end.  An omitted argument, a year end that is not a text literal or a filter in
    the CALCULATE filter list keeps the original call, which the validators refuse."""
    if isinstance(node, list):
        return [_rewrite_total_td(item) for item in node]
    if not isinstance(node, tuple) or not node:
        return node
    if node[0] == "call":
        function, arguments = node[1], node[2]
        in_filters = function in {"CALCULATE", "CALCULATETABLE"}
        new_arguments = tuple(_rewrite_total_td(argument, in_filters and index >= 1) for index, argument in enumerate(arguments))
        rewritten = (node[0], function, new_arguments, *node[3:])
        if function in _TOTAL_TO_DATES and not filter_position and 2 <= len(new_arguments) <= 4:
            expression, dates, rest = new_arguments[0], new_arguments[1], list(new_arguments[2:])
            if dates[0] != "reference" or any(item[0] == "omitted" for item in new_arguments):
                return rewritten
            year_end = None
            if function == "TOTALYTD" and rest and rest[-1][0] == "string" and (len(rest) == 2 or len(rest) == 1):
                year_end = rest.pop()
            if len(rest) > 1 or (rest and rest[0][0] == "string") or (function != "TOTALYTD" and len(new_arguments) > 3):
                return rewritten
            date_set = ("call", _TOTAL_TO_DATES[function], (dates,) if year_end is None else (dates, year_end))
            return ("call", "CALCULATE", (expression, date_set, *rest))
        return rewritten
    return tuple(_rewrite_total_td(child) if isinstance(child, (tuple, list)) else child for child in node)


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
    clean_expression = expression.strip(_DAX_WHITESPACE)
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
    seen: set[tuple[Any, ...]] = set()
    rows: list[dict[str, Any]] = []
    for source_row in source_candidate.rows:
        value = source_row.get(column)
        _reject_power_query_error(value, column, len(rows) + 1)
        key = cell_key(value)
        if key in seen:
            continue
        seen.add(key)
        rows.append({column: value})
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
    clean_expression = expression.strip(_DAX_WHITESPACE)
    parsed_expression = parse_expression(clean_expression)
    if _contains_function_call(parsed_expression, "COALESCE"):
        raise MeasureError(
            "COALESCE is supported only in measures in this local subset."
        )
    if any(
        _contains_function_call(parsed_expression, function)
        for function in ("COUNTX", "COUNTAX")
    ):
        raise MeasureError(
            "COUNTX and COUNTAX are supported only in measures in this local subset."
        )
    if any(
        _contains_function_call(parsed_expression, function)
        for function in ("USERELATIONSHIP", "CROSSFILTER")
    ):
        raise MeasureError(
            "Relationship filter modifiers are supported only for measures in this local subset."
        )
    if any(
        _contains_function_call(parsed_expression, function)
        for function in ("MAXX", "MINX")
    ):
        raise MeasureError(
            "MAXX and MINX are supported only in measures in this local subset."
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
                _reject_power_query_error(raw, actual, row_index)
                value = "" if raw is None else cell_to_text(raw).strip()
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
            if kind == "blank":
                return None
            if kind == "unary":
                operand = evaluate(node[2], row, row_index)
                if operand is None:
                    return None
                value = as_number(operand)
                return value if node[1] == "+" else -value
            if kind == "binary":
                left = evaluate(node[2], row, row_index)
                right = evaluate(node[3], row, row_index)
                if node[1] == "/" and left is not None and (right is None or as_number(right) == 0):
                    raise _DivisionError(f"Calculated column {name!r} divides by zero at row {row_index}.")
                return _binary_value(
                    node[1],
                    None if left is None else as_number(left),
                    None if right is None else as_number(right),
                )
            if kind == "logical":
                left = as_boolean(_consume_infinity(lambda: evaluate(node[2], row, row_index)))
                if node[1] == "&&":
                    return left and as_boolean(_consume_infinity(lambda: evaluate(node[3], row, row_index)))
                return left or as_boolean(_consume_infinity(lambda: evaluate(node[3], row, row_index)))
            if kind == "comparison":
                left = _consume_infinity(lambda: evaluate(node[2], row, row_index))
                right = _consume_infinity(lambda: evaluate(node[3], row, row_index))
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
                if as_boolean(_consume_infinity(lambda: evaluate(arguments[0], row, row_index))):
                    return evaluate(arguments[1], row, row_index)
                return evaluate(arguments[2], row, row_index) if len(arguments) == 3 else None
            if function == "ISBLANK":
                return _consume_infinity(lambda: evaluate(arguments[0], row, row_index)) is None
            if function == "IFERROR":
                try:
                    return evaluate(arguments[0], row, row_index)
                except (MeasureRuntimeError, DecimalException, OverflowError):
                    return evaluate(arguments[1], row, row_index)
            if function == "SWITCH":
                subject = _consume_infinity(lambda: evaluate(arguments[0], row, row_index))
                remaining = list(arguments[1:])
                fallback = remaining.pop() if len(remaining) % 2 else None
                for candidate, result in zip(remaining[::2], remaining[1::2]):
                    if dax_typed.values_match(
                        subject, _consume_infinity(lambda: evaluate(candidate, row, row_index))
                    ):
                        return evaluate(result, row, row_index)
                return None if fallback is None else evaluate(fallback, row, row_index)
            if function in {"AND", "OR"}:
                left = as_boolean(_consume_infinity(lambda: evaluate(arguments[0], row, row_index)))
                if function == "AND":
                    return left and as_boolean(_consume_infinity(lambda: evaluate(arguments[1], row, row_index)))
                return left or as_boolean(_consume_infinity(lambda: evaluate(arguments[1], row, row_index)))
            if function == "NOT":
                return not as_boolean(_consume_infinity(lambda: evaluate(arguments[0], row, row_index)))
            if function == "ABS":
                return abs(as_number(evaluate(arguments[0], row, row_index)))
            if function in _SCALAR_MATH_ARITY:
                return _scalar_math(function, [
                    None if value is None else as_number(value)
                    for value in (evaluate(argument, row, row_index) for argument in arguments)
                ])
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
            row[name] = value
        output_headers.append(name)
        output_types[name] = column_type

    return output_headers, output_rows, output_types


def normalize_measure(
    name: Any,
    expression: Any,
    *,
    description: Any = "",
    display_folder: Any = "",
    is_hidden: Any = False,
    home_table_id: Any = None,
) -> dict[str, Any]:
    """Validate a persisted measure and its model metadata."""
    if not isinstance(name, str) or not name.strip():
        raise MeasureError("Enter a measure name.")
    clean_name = name.strip()
    if len(clean_name) > 120 or any(char in clean_name for char in "[\r\n"):
        raise MeasureError("Measure names must be 1–120 characters and cannot contain brackets or line breaks.")
    if not isinstance(expression, str):
        raise MeasureError("A measure expression must be text.")
    clean_expression = expression.strip(_DAX_WHITESPACE)
    # Accept a complete DAX assignment in the expression box as a convenience.
    assignment = _FORMULA_ASSIGNMENT.match(clean_expression)
    if assignment is not None:
        assignment_name = (
            (assignment.group("bracketed") or "").replace("]]", "]") or assignment.group("plain") or ""
        ).strip()
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
    if (
        not isinstance(description, str)
        or len(description) > 4_000
        or "\x00" in description
    ):
        raise MeasureError("A measure description must be at most 4,000 characters and contain no null characters.")
    if (
        not isinstance(display_folder, str)
        or len(display_folder) > 400
        or any(ord(char) < 32 for char in display_folder)
    ):
        raise MeasureError("A measure display folder must be at most 400 characters and contain no control characters.")
    if type(is_hidden) is not bool:
        raise MeasureError("A measure is_hidden value must be true or false.")
    result: dict[str, Any] = {"name": clean_name, "expression": clean_expression}
    if home_table_id is not None:
        if not isinstance(home_table_id, str) or not home_table_id.strip():
            raise MeasureError("A measure home table ID must be non-empty text.")
        result["home_table_id"] = home_table_id.strip()
    if description.strip():
        result["description"] = description.strip()
    if display_folder.strip():
        result["display_folder"] = display_folder.strip().strip("/\\")
        if not result["display_folder"]:
            result.pop("display_folder")
    if is_hidden:
        result["is_hidden"] = True
    return result


def validate_measures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_MEASURES:
        raise MeasureError(f"A model can contain at most {MAX_MEASURES} measures.")
    result = []
    names: set[str] = set()
    supported_fields = {
        "name", "expression", "description", "display_folder", "is_hidden",
        "home_table_id",
    }
    for index, item in enumerate(value, 1):
        if (
            not isinstance(item, dict)
            or not {"name", "expression"}.issubset(item)
            or set(item) - supported_fields
        ):
            raise MeasureError(
                f"Measure {index} needs name and expression and supports only recognized metadata fields."
            )
        measure = normalize_measure(
            item["name"],
            item["expression"],
            description=item.get("description", ""),
            display_folder=item.get("display_folder", ""),
            is_hidden=item.get("is_hidden", False),
            home_table_id=item.get("home_table_id"),
        )
        key = measure["name"].casefold()
        if key in names:
            raise MeasureError(f"Measure {measure['name']!r} is duplicated.")
        names.add(key)
        result.append(measure)
    return result


def _cell_date_value(value: Any, column: str, row_index: int | None) -> Any:
    """A Date/DateTime model cell as a DAX DateTime (None when blank)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (date, datetime)):
        return dax_dates.from_datetime(value)
    try:
        return dax_dates.from_datetime(datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")))
    except ValueError:
        return dax_dates.parse_date_text(str(value))


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


def _shift_date(value: date, intervals: int, unit: str, keep_month_end: bool = False) -> date:
    """value moved by whole months / quarters / years (days for DAY); the day is clamped to the target month, and with
    keep_month_end the last day of a month stays the last day of the target month (live DATESINPERIOD)."""
    if unit == "DAY":
        try:
            return value + timedelta(days=intervals)
        except OverflowError as exc:
            raise MeasureError("DATEADD shifted dates outside the supported date range.") from exc
    target_index = value.year * 12 + value.month - 1 + intervals * {"MONTH": 1, "QUARTER": 3, "YEAR": 12}[unit]
    target_year, zero_based_month = divmod(target_index, 12)
    target_month = zero_based_month + 1
    if not 1 <= target_year <= 9999:
        raise MeasureError("DATEADD shifted dates outside the supported date range.")
    last = monthrange(target_year, target_month)[1]
    if keep_month_end and value.day == monthrange(value.year, value.month)[1]:
        return date(target_year, target_month, last)
    return date(target_year, target_month, min(value.day, last))


def _sparse_period_window(days: set[date], start: date, count: int, unit: str) -> set[date] | None:
    """DATESINPERIOD month / quarter / year window over a sparse date column (one that is not a full calendar), measured on live Power
    BI in iteration 84 (13,608 probes on two fact date columns).

    A negative count: when the month of the start date holds no later date of the column the start date stands for the end of its
    month, so the window is whole months (from the 1st of the month |n|-1 months back); otherwise it is the exact DAX window.
    0 of 2,268 probes differ.  A positive count has no rule that fits every probe: four readings of the window (exact days, whole
    months, the exact end taken to the end of its month, with and without that last day) are computed and the answer is given only
    where they agree (2,058 of 2,268 probes, 0 wrong); None means "refuse"."""
    boundary = _shift_date(start, count, unit, keep_month_end=True)
    months = abs(count) * {"MONTH": 1, "QUARTER": 3, "YEAR": 12}[unit]

    def month_end(day: date) -> date:
        return date(day.year, day.month, monthrange(day.year, day.month)[1])

    if count < 0:
        exact = {value for value in days if boundary < value <= start}
        if any(start < value <= month_end(start) for value in days):
            return exact
        year, zero_month = divmod(start.year * 12 + start.month - 1 - (months - 1), 12)
        first = date(year, zero_month + 1, 1) if year >= 1 else date.min
        return {value for value in days if first <= value <= start}
    year, zero_month = divmod(start.year * 12 + start.month - 1 + months, 12)
    readings = [
        {value for value in days if start <= value < boundary},
        {value for value in days if start <= value <= (month_end(date(year, zero_month + 1, 1)) if year <= 9999 else date.max)},
        {value for value in days if start <= value < month_end(boundary)},
        {value for value in days if start <= value <= month_end(boundary - timedelta(days=1))},
    ]
    return readings[0] if all(reading == readings[0] for reading in readings) else None


def _scalar_day(value: Any, function: str) -> date | None:
    """A date-set bound as a calendar day: BLANK is None, a date or number is truncated to its day, text is an ISO / date text."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise MeasureError(f"{function} needs a date value.")
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text)
        except ValueError:
            try:
                value = dax_dates.parse_date_text(text)
            except Exception as exc:
                raise MeasureError(f"{function} needs a date value.") from exc
    if not isinstance(value, Decimal) or not value.is_finite():
        raise MeasureError(f"{function} needs a date value.")
    try:
        return dax_dates.to_datetime(value.to_integral_value(rounding=ROUND_FLOOR), ROUND_FLOOR).date()
    except (OverflowError, ValueError, MeasureError) as exc:
        raise MeasureError(f"{function} needs a date inside the supported range.") from exc


def _scalar_count(value: Any) -> int:
    """number_of_intervals: BLANK and 0 are no period, text numbers are coerced, halves round away from zero."""
    if value is None:
        return 0
    if isinstance(value, str):
        try:
            value = Decimal(value.strip())
        except DecimalException as exc:
            raise MeasureError("number_of_intervals must be a number.") from exc
    if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite():
        raise MeasureError("number_of_intervals must be a number.")
    rounded = int(value.to_integral_value(rounding=ROUND_HALF_UP))  # ROUND_HALF_UP rounds halves away from zero
    if abs(rounded) > 3_652_059:
        raise MeasureError("number_of_intervals is outside the supported range.")
    return rounded


def _gap_free(dates: Iterable[date]) -> bool:
    values = sorted(set(dates))
    return bool(values) and (values[-1] - values[0]).days + 1 == len(values)


def _dateadd_dates(
    selected_dates: Iterable[date], intervals: int, interval: str, available_dates: Iterable[date] | None = None
) -> set[date]:
    """Shift a date-column selection by DATEADD intervals (live Power BI 2.157, 728 of 728 probes).

    A contiguous selection becomes the whole range from the shifted first day to the shifted last day, the last day moved to the
    end of its month when the selection has several days and ends on its month end (QUARTER and YEAR too). A selection that is not
    contiguous is shifted day by day when the date column is unique and gap free (available_dates), otherwise refused."""
    source_dates = sorted(set(selected_dates))
    unit = interval.upper()
    if unit not in {"YEAR", "QUARTER", "MONTH", "DAY"}:
        raise MeasureError("DATEADD date-column intervals support YEAR, QUARTER, MONTH, or DAY.")
    if not source_dates:
        return set()
    contiguous = len(source_dates) == 1 or _gap_free(source_dates)
    try:
        if not contiguous:
            if available_dates is None or not _gap_free(available_dates):
                raise MeasureError("DATEADD requires the current date-column selection to be contiguous.")
            runs: list[list[date]] = [[source_dates[0]]]
            for value in source_dates[1:]:
                if (value - runs[-1][-1]).days == 1:
                    runs[-1].append(value)
                else:
                    runs.append([value])
            result: set[date] = set()
            for run in runs:
                result |= _dateadd_dates(run, intervals, interval)
            return result
        if unit == "DAY":
            return {_shift_date(value, intervals, unit) for value in source_dates}
        first = _shift_date(source_dates[0], intervals, unit)
        last = _shift_date(source_dates[-1], intervals, unit)
        if len(source_dates) > 1 and source_dates[-1].day == monthrange(source_dates[-1].year, source_dates[-1].month)[1]:
            last = date(last.year, last.month, monthrange(last.year, last.month)[1])
        return {first + timedelta(days=offset) for offset in range((last - first).days + 1)}
    except MeasureError:
        raise
    except (OverflowError, ValueError) as exc:
        raise MeasureError("DATEADD shifted dates outside the supported date range.") from exc


def _sameperiodlastyear_dates(selected_dates: Iterable[date], available_dates: Iterable[date] | None = None) -> set[date]:
    """SAMEPERIODLASTYEAR is DATEADD(-1, YEAR) (live Power BI: 43 of 43 contexts, the leap day included)."""
    try:
        return _dateadd_dates(selected_dates, -1, "YEAR", available_dates)
    except MeasureError as error:
        raise MeasureError(str(error).replace("DATEADD", "SAMEPERIODLASTYEAR")) from error


# Functions and operators whose arguments are evaluated in the caller's context: a bare column below them still has no row context.
_ROW_CONTEXT_FREE_CALLS = {
    "IF", "SWITCH", "COALESCE", "IFERROR", "AND", "OR", "NOT", "ISBLANK", "ABS", "EXACT",
    "UPPER", "LOWER", "LEN", "TRIM", "ROUND", "INT",
}
_ROW_CONTEXT_FREE_NODES = {"binary", "comparison", "logical", "unary", "concat", "in", "let", "tableconstructor", "strict_equal"}


def _bare_column_outside_row_context(node: Any, columns: dict[str, set[str]]) -> tuple[str, str] | None:
    """The first column reference that a measure evaluated without a row context reads directly.

    Power BI refuses such a reference when the query is compiled ("A single value for column ... cannot be
    determined"), also in an IF/SWITCH branch that would never run.  Only constructs that keep the caller's
    context are followed; aggregations, iterators, CALCULATE and table functions give their arguments their own
    context and end the search.
    """
    if not isinstance(node, tuple) or not node:
        return None
    kind = node[0]
    if kind == "reference":
        table, column = node[1], node[2]
        if table and column.casefold() in columns.get(table.casefold(), ()):
            return table, column
        return None
    if kind == "call":
        if node[1] not in _ROW_CONTEXT_FREE_CALLS:
            return None
        children = node[2]
    elif kind == "let":
        children = [value for _name, value in node[1]] + [node[2]]
    elif kind == "in":
        children = [node[1]]
    elif kind in _ROW_CONTEXT_FREE_NODES:
        children = [part for part in node[1:] if isinstance(part, tuple)]
    else:
        return None
    for child in children:
        found = _bare_column_outside_row_context(child, columns)
        if found:
            return found
    return None


def _measure_references(node: Any, found: set[str]) -> None:
    if isinstance(node, tuple):
        if len(node) == 3 and node[0] == "reference" and node[1] == "":
            found.add(str(node[2]).casefold())
        for part in node:
            _measure_references(part, found)
    elif isinstance(node, (list, frozenset)):
        for part in node:
            _measure_references(part, found)


def _reject_bare_columns_without_row_context(
    selected: list[tuple[dict[str, str], tuple[Any, ...]]],
    every_expression: list[tuple[Any, ...]],
    columns: dict[str, set[str]],
) -> None:
    referenced: set[str] = set()
    for expression in every_expression:
        _measure_references(expression, referenced)
    for item, expression in selected:
        if item["name"].casefold() in referenced:
            continue  # used inside another measure, which may supply a row context
        found = _bare_column_outside_row_context(expression, columns)
        if found:
            raise MeasureError(
                f"A single value for column '{found[1]}' in table '{found[0]}' cannot be determined. "
                "Refer to the column inside an aggregation such as MIN, MAX, COUNT or SUM, or iterate its table."
            )



_NUMBER_COLUMN_TYPES = {"whole_number", "decimal_number", "decimal", "fixed_decimal", "currency", "number", "int64", "double"}
_TEXT_FUNCTIONS = {"UPPER", "LOWER", "TRIM", "LEFT", "RIGHT", "MID", "CONCATENATE", "FORMAT", "SUBSTITUTE", "REPT", "FIXED", "NAMEOF", "CUSTOMDATA"}
_BOOLEAN_FUNCTIONS = {"AND", "OR", "NOT", "ISBLANK", "EXACT", "ISNUMBER", "ISTEXT", "ISERROR", "CONTAINSROW", "CONTAINS"}


def _static_type(node: Any, columns: dict[str, dict[str, str]], variables: dict[str, str | None]) -> str | None:
    """text / number / boolean when the expression has that type whatever the data, else None (unknown or mixed).

    Power BI checks the operands of a comparison against each other when it compiles the query, so a BLANK() result
    of an expression typed Text still cannot be compared with a number."""
    if not isinstance(node, tuple) or not node:
        return None
    kind = node[0]
    if kind == "number":
        return "number"
    if kind == "string":
        return "text"
    if kind == "boolean":
        return "boolean"
    if kind in {"comparison", "logical", "in", "strict_equal"}:
        return "boolean"
    if kind == "unary" and node[1] == "+" and _static_type(node[2], columns, variables) == "boolean":
        return "boolean"  # unary plus leaves a True/False a True/False (live Power BI, iteration 87)
    if kind in {"binary", "unary"}:
        return "number"
    if kind == "concat":
        return "text"
    if kind == "var":
        return variables.get(str(node[1]))
    if kind == "reference":
        if not node[1]:
            return None
        column_type = columns.get(node[1].casefold(), {}).get(str(node[2]).casefold())
        if not column_type:
            return None
        if column_type in _NUMBER_COLUMN_TYPES:
            return "number"
        if column_type in {"boolean", "true_false"}:
            return "boolean"
        return "text" if column_type == "text" else None  # dates are compared with ISO text literals
    if kind == "let":
        scope = dict(variables)
        for name, value in node[1]:
            scope[str(name)] = _static_type(value, columns, scope)
        return _static_type(node[2], columns, scope)
    if kind != "call":
        return None
    function, arguments = node[1], node[2]
    if function in {"SELECTEDVALUE", "LOOKUPVALUE"} and arguments:
        return _static_type(arguments[0], columns, variables)
    if function in _TEXT_FUNCTIONS:
        return "text"
    if function in _BOOLEAN_FUNCTIONS:
        return "boolean"
    if function in {"IF", "IF.EAGER", "COALESCE", "IFERROR", "SWITCH"}:
        if function in {"IF", "IF.EAGER"}:
            results = list(arguments[1:])
        elif function == "SWITCH":
            results = [arguments[index] for index in range(2, len(arguments), 2)]
            if len(arguments) >= 4 and len(arguments) % 2 == 0:
                results.append(arguments[-1])
        else:
            results = list(arguments)
        if not results:
            return None
        types = {_static_type(result, columns, variables) for result in results if result[0] != "blank"}
        if not types:
            return "number"  # a conditional that can only give BLANK() is typed Integer
        return types.pop() if len(types) == 1 and None not in types else None
    return None


def _reject_mismatched_comparison_types(node: Any, columns: dict[str, dict[str, str]], variables: dict[str, str | None] | None = None) -> None:
    variables = {} if variables is None else variables
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "let":
        scope = dict(variables)
        for name, value in node[1]:
            _reject_mismatched_comparison_types(value, columns, scope)
            scope[str(name)] = _static_type(value, columns, scope)
        _reject_mismatched_comparison_types(node[2], columns, scope)
        return
    if node[0] == "reference" and node[1] and columns:
        known = columns.get(str(node[1]).casefold())
        if known is None:
            raise MeasureError(f"Cannot find table '{node[1]}'.")
        if str(node[2]).casefold() not in known:
            raise MeasureError(f"Column '{node[2]}' in table '{node[1]}' cannot be found or may not be used in this expression.")
    if node[0] == "call" and node[1] in {"EARLIER", "EARLIEST"} and len(node[2]) == 2:
        level = node[2][1]
        if level[0] != "number" or level[1] != level[1].to_integral_value() or level[1] < 1 or level[1].as_tuple().exponent > 0 or "." in str(level[1]):
            raise MeasureError("The second argument of function EARLIER must be an integer greater than zero.")
    if node[0] == "call":
        function, arguments = node[1], node[2]
        if function in {"SUMX", "AVERAGEX", "PRODUCTX", "MEDIANX", "MAXX", "MINX"} and len(arguments) >= 2:
            result_type = _static_type(arguments[1], columns, variables)
            if result_type == "boolean" or (result_type == "text" and function in {"SUMX", "AVERAGEX", "PRODUCTX", "MEDIANX"}):
                raise MeasureError(f"The function {function} cannot work with values of type {'Boolean' if result_type == 'boolean' else 'String'}.")
        elif function in {"SUM", "AVERAGE"} and len(arguments) == 1 and _static_type(arguments[0], columns, variables) == "text":
            raise MeasureError(f"The function {function} cannot work with values of type String.")
        elif function in {"MIN", "MAX"} and len(arguments) == 2 and all(_static_type(argument, columns, variables) == "boolean" for argument in arguments):
            raise MeasureError("Min or Max of booleans are not currently supported.")
        elif function in {"MIN", "MAX"} and len(arguments) == 2 and {_static_type(argument, columns, variables) for argument in arguments} == {"text", "number"}:
            raise MeasureError(f"The function {function} cannot compare text with a number.")
        elif function == "NAMEOF":
            arg = arguments[0]
            if arg[0] == "table":
                if columns and str(arg[1]).casefold() not in columns:
                    raise MeasureError("Only measure or fully-qualified column or table or calendar references are allowed in NAMEOF function.")
        elif function in {"ISONORAFTER", "ISAFTER"}:
            for i in range(0, len(arguments) - 1, 3):
                left_t = _static_type(arguments[i], columns, variables)
                right_t = _static_type(arguments[i + 1], columns, variables)
                if left_t and right_t and left_t != right_t:
                    t1 = "Integer" if left_t == "number" else ("Text" if left_t == "text" else "True/False")
                    t2 = "Integer" if right_t == "number" else ("Text" if right_t == "text" else "True/False")
                    raise MeasureError(
                        f"DAX comparison operations do not support comparing values of type {t1} with values of type {t2}. "
                        "Consider using the VALUE or FORMAT function to convert one of the values."
                    )
    if node[0] == "comparison":
        left, right = _static_type(node[2], columns, variables), _static_type(node[3], columns, variables)
        if left and right and left != right:
            raise MeasureError(
                f"DAX comparison operations do not support comparing values of type {left} with values of type {right}. "
                "Consider using the VALUE or FORMAT function to convert one of the values."
            )
    for part in node[1:]:
        if isinstance(part, tuple) and part and isinstance(part[0], str):
            _reject_mismatched_comparison_types(part, columns, variables)
        elif isinstance(part, (tuple, list, frozenset)):
            for item in part:
                if isinstance(item, tuple):
                    _reject_mismatched_comparison_types(item, columns, variables)



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
    visual_axis_context: VisualAxisContext | None = None,
) -> dict[str, Decimal | None]:
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
    if visual_axis_context is not None:
        if not isinstance(visual_axis_context, VisualAxisContext):
            raise MeasureError("The visual axis filter context is invalid.")
        axis_table = contexts_by_id.get(visual_axis_context.table_id)
        if axis_table is None:
            raise MeasureError("The chart axis table is not loaded in the model.")
        axis_columns = {
            column.casefold(): column for column in axis_table["headers"]
        }
        axis_column = axis_columns.get(visual_axis_context.column.casefold())
        if axis_column is None:
            raise MeasureError("The chart axis column is not loaded in the model.")
        selected_rows = visual_axis_context.selected_rows
        if selected_rows is not None and any(
            type(index) is not int or not 0 <= index < len(axis_table["rows"])
            for index in selected_rows
        ):
            raise MeasureError("The chart axis selection has invalid row indexes.")
        if (
            visual_axis_context.blank_allowed is not None
            and type(visual_axis_context.blank_allowed) is not bool
        ):
            raise MeasureError("The chart axis selection has invalid blank provenance.")
        if any(table_id not in contexts_by_id for table_id in visual_axis_context.filter_table_ids):
            raise MeasureError("The chart axis selection references an unavailable table.")
        visual_axis_context = VisualAxisContext(
            table_id=visual_axis_context.table_id,
            column=axis_column,
            selected_rows=(
                None if selected_rows is None else frozenset(selected_rows)
            ),
            blank_allowed=visual_axis_context.blank_allowed,
            filter_table_ids=frozenset(visual_axis_context.filter_table_ids),
        )
    evaluation_contexts_by_id = contexts_by_id
    evaluation_filter_ids = set(filter_ids)
    relationship_definitions = list(relationships)
    related_lookup_cache: dict[
        tuple[str, str, str, str, str],
        dict[tuple[str, Any], list[dict[str, Any]]],
    ] = {}

    table_names: dict[str, list[dict[str, Any]]] = {}
    for context in contexts_by_id.values():
        table_names.setdefault(context["name"].casefold(), []).append(context)

    try:
        unknown_member_ids = unknown_member_table_ids(
            list(contexts_by_id.values()), relationship_definitions
        )
    except (RelationshipError, DecimalException) as exc:
        raise MeasureError(f"Could not inspect model relationships: {exc}") from exc
    unknown_member_exclusions: dict[str, set[str] | None] = {}

    def unknown_member_hidden(table_id: str) -> bool:
        """ALLNOBLANKROW(T) removes the blank member from every view of T; ALLNOBLANKROW(T[column]) only keeps the rows that
        point at it out of the facts (live Power BI: VALUES(T[c]) still lists it, SUM over the facts drops its rows)."""
        return table_id in unknown_member_exclusions and unknown_member_exclusions[table_id] is None

    def own_unknown_member_selected(context: dict[str, Any], ignore_exclusion: bool = False) -> bool:
        """Do the filters on this table itself still select its virtual blank member (the predicate holds for a row of BLANKs)?"""
        table_id = context["id"]
        if table_id in unknown_member_exclusions and not ignore_exclusion:
            return False
        if "filter_table_rows" in context:
            return bool(context.get("filter_table_unknown", False))  # FILTER(VALUES(T)..) lists it, FILTER(T,..) never does
        blank_allowed = context.get("filter_column_blank_allowed", {})
        if not context.get("filter_column_rows") and "filter_rows" in context:
            return False  # rows supplied by a visual or slicer without per-column provenance: a selection never includes the blank
        return all(blank_allowed.get(column, False) for column in context.get("filter_column_rows", {}))

    def typed_cell(context: dict[str, Any], column: str, raw: Any) -> Any:
        """A loaded cell as the DAX value of its column type (None is blank)."""
        if raw is None:
            return None
        kind = str(context.get("column_types", {}).get(column, "text")).casefold()
        if kind in {"whole_number", "decimal_number", "decimal", "fixed_decimal", "currency", "number", "int64", "double"}:
            return raw if isinstance(raw, Decimal) else dax_typed.text_to_number(cell_to_text(raw))
        if kind in {"date", "datetime"}:
            return _cell_date_value(raw, column, None)
        if kind == "boolean":
            return raw if isinstance(raw, bool) else cell_to_text(raw).strip().casefold() == "true"
        return raw if isinstance(raw, str) else cell_to_text(raw)

    # What ALLSELECTED sees inside an iterator (tools/parity/dax_battery_allselected_shadow.json): the iterated table's
    # distinct tuples ("shadow", one component over the columns it came from), the outer filters those columns replace
    # ("suppressed"), and the filters that are only a context transition ("transition", which it never sees).
    eff_layers: tuple[_Shadow, ...] = ()
    eff_suppressed: dict[str, dict[str, Any]] = {}  # table -> casefolded column -> the outer filter object the shadow replaced
    eff_transition: dict[str, dict[str, tuple[Any, Any]]] = {}  # table -> casefolded column -> (filter a transition set, filter it replaced)
    eff_group_keys: dict[str, dict[str, Any]] = {}  # SUMMARIZE group keys: table -> casefolded column -> the filter object
    eff_touched: frozenset[tuple[str, str]] = frozenset()  # (table, column) a CALCULATE modifier has cleared or filtered
    eff_blocked = False
    eff_rank_table = False  # evaluating the table argument of RANKX: ALLSELECTED(col) still sees a SUMMARIZE key on its own column

    shadowed_cache: list[frozenset[str]] = []

    def shadowed_measure_keys() -> frozenset[str]:
        """Lower-case names of the measures that share their name with a column of their own table."""
        if not shadowed_cache:
            keys = set()
            for definition in definitions:
                home = contexts_by_id.get(str(definition.get("home_table_id") or ""))
                if home is not None and definition["name"].casefold() in {str(header).casefold() for header in home["headers"]}:
                    keys.add(definition["name"].casefold())
            shadowed_cache.append(frozenset(keys))
        return shadowed_cache[0]

    one_to_one_unmatched_cache: dict[str, tuple[frozenset[int], bool]] = {}

    def one_to_one_unmatched(table_id: str) -> tuple[frozenset[int], bool]:
        """(rows of this table with no partner across a one-to-one relationship, whether the table at the other end has such rows)."""
        if table_id not in one_to_one_unmatched_cache:
            own: set[int] = set()
            other_has = False
            for relationship in relationship_definitions:
                if not isinstance(relationship, dict) or relationship.get("cardinality") != "one_to_one":
                    continue
                ends = {
                    str(relationship.get("from_table_id")): str(relationship.get("from_column")),
                    str(relationship.get("to_table_id")): str(relationship.get("to_column")),
                }
                if table_id not in ends or len(ends) != 2:
                    continue
                other_id = next(identifier for identifier in ends if identifier != table_id)
                if other_id not in contexts_by_id:
                    continue

                def keys(identifier: str) -> list[Any]:
                    context = contexts_by_id[identifier]
                    return [cell_key(ascii_fold(v) if isinstance(v, str) else v) for v in (
                        typed_cell(context, ends[identifier], row.get(ends[identifier])) for row in context["rows"])]

                mine, theirs = keys(table_id), keys(other_id)
                blank = cell_key(None)
                present_theirs, present_mine = set(theirs) - {blank}, set(mine) - {blank}
                own |= {index for index, key in enumerate(mine) if key == blank or key not in present_theirs}
                other_has = other_has or any(key == blank or key not in present_mine for key in theirs)
            one_to_one_unmatched_cache[table_id] = (frozenset(own), other_has)
        return one_to_one_unmatched_cache[table_id]

    def refuse_one_to_one_blank_reader(table_id: str, what: str, any_filter: bool = False) -> None:
        """Live Power BI (iteration 84, critic; 6 of 1,033 fresh ZM probes): reading the values of a table of a one-to-one relationship that has
        unmatched rows, while the pair is filtered, lists the blank members of both ends in a way not modelled here
        (CALCULATE(SELECTEDVALUE(U[K],"x"), NOT(U[X]="x1"), W[K]=BLANK()) is "x", ours "k4")."""
        for relationship in relationship_definitions:
            if not isinstance(relationship, dict) or not relationship.get("is_active") or relationship.get("cardinality") != "one_to_one":
                continue
            ends = (str(relationship.get("from_table_id")), str(relationship.get("to_table_id")))
            if table_id not in ends or len(set(ends)) != 2:
                continue
            if any(
                end in evaluation_filter_ids and not eff_transition.get(end) and not eff_group_keys.get(end) and end in evaluation_contexts_by_id
                and (any_filter or own_unknown_member_selected(evaluation_contexts_by_id[end]))
                and not (any_filter and end == table_id)  # ALLSELECTED: only the partner's filter is out of reach (the table's own filter stays)
                for end in ends
            ) and any(one_to_one_unmatched(end)[0] for end in ends):
                raise MeasureError(f"{what} over a table of a one-to-one relationship with unmatched rows is not supported while it is filtered in the local engine.")

    def refuse_one_to_one_values_iteration(table_node: tuple[Any, ...]) -> None:
        """Live Power BI (iteration 84, testing agent): SUMX(VALUES(W[Y]), CALCULATE(SUM(F[Amt]))) with the partner U filtered so that one of
        its rows without a partner in W stays visible adds the blank member of W to the iteration (CALCULATE(.., U[K]="k4") is 16 where
        COUNTROWS(VALUES(W[Y])) and CONCATENATEX over the same VALUES list no blank).  Which functions list it is not modelled, so this is refused."""
        if table_node[0] != "table_call" or table_node[1] not in {"VALUES", "DISTINCT"} or not table_node[2]:
            return
        source = table_node[2]
        try:
            if source[0] == "reference":
                iterated = resolve_table(source[1], source[2])[0]
            elif source[0] == "table":
                iterated = resolve_table_context(str(source[1]))
            else:
                return
        except MeasureError:
            return
        for relationship in relationship_definitions:
            if not isinstance(relationship, dict) or not relationship.get("is_active") or relationship.get("cardinality") != "one_to_one":
                continue
            ends = (str(relationship.get("from_table_id")), str(relationship.get("to_table_id")))
            if iterated["id"] not in ends or len(set(ends)) != 2:
                continue
            partner = next(end for end in ends if end != iterated["id"])
            held = evaluation_contexts_by_id.get(iterated["id"], {})
            if held.get("filter_column_rows") and not eff_transition.get(iterated["id"]) and all(
                isinstance(rows, BlankSet) and rows.blank and rows.peer for rows in held["filter_column_rows"].values()
            ):  # the iterated table was reached through the orphan row of its partner by a table filter (a fact filter FILTER(F, ..))
                raise MeasureError("Iterating the values of a table of a one-to-one relationship narrowed through its partner's orphan row is not supported in the local engine.")
            if partner not in evaluation_filter_ids or partner not in contexts_by_id:
                continue
            own = one_to_one_unmatched(partner)[0]
            partner_rows = contexts_by_id[partner]["rows"]
            orphans = {id(partner_rows[index]) for index in own}
            if any(id(row) in orphans for row in rows_by_table_id.get(partner, ())):
                raise MeasureError("Iterating the values of a table of a one-to-one relationship whose filtered partner keeps rows without a partner is not supported in the local engine.")

    def refuse_one_to_one_pair_filters(tables: list[dict[str, Any]], filter_table_ids: set[Any]) -> None:
        """Live Power BI (iteration 84, critic; fresh ZM probes): when a filter on one table of a one-to-one relationship keeps only rows that
        have no partner and the filter on the other table keeps real rows and selects its own blank member, which blank members and orphan rows
        meet is not modelled here (CALCULATE(DISTINCTCOUNT(F[K]), U[K]<>"k5", W[Y]="y5") is BLANK, ours 1), so that pair is refused."""
        by_id = {str(table.get("id")): table for table in tables}
        for relationship in relationship_definitions:
            if not isinstance(relationship, dict) or not relationship.get("is_active") or relationship.get("cardinality") != "one_to_one":
                continue
            ends = (str(relationship.get("from_table_id")), str(relationship.get("to_table_id")))
            if len(set(ends)) != 2 or any(end not in filter_table_ids or end not in by_id or eff_transition.get(end) for end in ends):
                continue

            def visible_rows(table: dict[str, Any]) -> Any:
                visible: Any = None
                for rows in table.get("filter_column_rows", {}).values():
                    visible = frozenset(rows) if visible is None else visible & frozenset(rows)
                if "filter_table_rows" in table:
                    held = frozenset(table["filter_table_rows"])
                    visible = held if visible is None else visible & held
                return visible

            for mine, theirs in (ends, ends[::-1]):
                own, _other_has = one_to_one_unmatched(mine)
                kept, partner = visible_rows(by_id[mine]), visible_rows(by_id[theirs])
                if kept and kept <= own and partner and own_unknown_member_selected(by_id[theirs]):
                    raise MeasureError("Filters on both tables of a one-to-one relationship are not supported in the local engine.")

    def propagate_relationship_filters(
        tables: list[dict[str, Any]], relationships: list[dict[str, Any]], filter_table_ids: Any,
        ignore_exclusions: Iterable[str] = (),
    ) -> dict[str, list[dict[str, Any]]]:
        """Relationship propagation that also carries the virtual blank member: fact rows whose key has no match in a
        one-side table stay while that table's own filters still select its blank member."""
        refuse_one_to_one_pair_filters(tables, set(filter_table_ids))
        ignored = set(ignore_exclusions)
        excluded = {table_id for table_id in unknown_member_exclusions if table_id in unknown_member_ids and table_id not in ignored}
        filter_table_ids = set(filter_table_ids) | excluded  # ALLNOBLANKROW leaves no filter on its table, only the missing blank member
        selected = {
            str(table.get("id")): own_unknown_member_selected(table, str(table.get("id")) in ignored)
            for table in tables if table.get("id") in filter_table_ids and table.get("id") in unknown_member_ids
        }
        peer_blank = {
            str(table.get("id")) for table in tables
            if table.get("id") in filter_table_ids and table.get("filter_column_rows")
            and all(getattr(rows, "peer", False) for rows in table["filter_column_rows"].values())
        }
        many_blank = {
            str(table.get("id")) for table in tables
            if table.get("id") in filter_table_ids and table.get("filter_column_rows")
            and all(getattr(rows, "many", False) for rows in table["filter_column_rows"].values())
        }
        return _propagate_relationship_filters(tables, relationships, filter_table_ids, selected, peer_blank=peer_blank, many_blank=many_blank)

    try:
        rows_by_table_id = propagate_relationship_filters(
            list(contexts_by_id.values()),
            relationship_definitions,
            filter_ids,
        )
    except RelationshipError as exc:
        raise MeasureError(f"Could not apply model relationships: {exc}") from exc

    value_cache: dict[tuple[str, int], Decimal | None] = {}
    resolving: set[str] = set()
    context_sequence = 0
    current_context = 0
    current_home_table_id = active_context["id"]

    for measure in definitions:
        home_table_id = measure.get("home_table_id")
        if home_table_id is not None and home_table_id not in contexts_by_id:
            raise MeasureError(
                f"Measure {measure['name']!r} has a home table that is not loaded."
            )

    def resolve_table_context(table: str) -> dict[str, Any]:
        if not table:
            return evaluation_contexts_by_id.get(
                current_home_table_id, active_context
            )
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

    def eff_active() -> bool:
        return not eff_blocked and (bool(eff_layers) or any(eff_transition.values()) or any(eff_suppressed.values()) or any(eff_group_keys.values()))

    def allselected_rows_for(source_context: dict[str, Any], columns: list[str]) -> list[dict[str, Any]] | None:
        """ALLSELECTED(columns) inside an iterator: the table rows that satisfy every filter touching those columns, where
        the filters are the iterator shadows, the explicit CALCULATE filters and the outer filters the shadows did not
        replace. Filters on other columns and the context transition do not count. None when the filter context cannot say."""
        table_id = source_context["id"]
        wanted = {column.casefold() for column in columns}
        cleared = {header.casefold() for header in source_context["headers"]} - wanted
        for folded, outer in eff_suppressed.get(table_id, {}).items():
            if current_filter(table_id, folded) is outer:  # still the outer filter the shadow replaced
                cleared.add(folded)
        for folded, key_rows in eff_group_keys.get(table_id, {}).items():
            if current_filter(table_id, folded) is key_rows:  # a group key still stands as the SUMMARIZE row set
                if folded in wanted and eff_rank_table:
                    cleared.discard(folded)  # Power BI: RANKX(ALLSELECTED(col), ...) in a SUMMARIZE column ranks within the group's key
                elif folded in wanted or any((table_id, name) in eff_touched for name in wanted):
                    cleared.add(folded)  # a key inside the columns asked for, or after a modifier touched them, drops out
                else:
                    cleared.discard(folded)  # a key outside them narrows the answer to its group
        replaced_outer: list[Any] = []
        for folded, (set_by_transition, outer) in eff_transition.get(table_id, {}).items():
            if current_filter(table_id, folded) is set_by_transition:  # still only the row's context transition
                cleared.add(folded)
                shadowed = eff_suppressed.get(table_id, {}).get(folded, _NOTHING)
                if folded in wanted and outer is not None and shadowed is not outer:
                    replaced_outer.append(outer)  # the outer filter the transition covered up is still in force for ALLSELECTED
        other_tables: dict[str, dict[str, Any]] = {}
        for other_id, tagged_columns in eff_transition.items():  # a row context of a related table also filtered the one-side tables
            if other_id == table_id:
                continue
            for folded, (set_by_transition, outer) in tagged_columns.items():
                if current_filter(other_id, folded) is set_by_transition:  # still only the row's transition: ALLSELECTED sees the outer filter it covered
                    other_tables.setdefault(other_id, {})[folded] = outer
        try:
            rows, _contexts, _roots = rows_after_clearing_columns(source_context, cleared, other_tables=other_tables)
        except MeasureError:
            return None
        full = source_context["rows"]
        if replaced_outer:
            keep_positions = set.intersection(*(set(outer) for outer in replaced_outer))
            visible = {id(row) for row in rows}
            rows = [row for position, row in enumerate(full) if position in keep_positions and id(row) in visible]
        allowed = {id(row) for row in rows}
        result = [row for row in full if id(row) in allowed] if len(allowed) != len(full) or any(id(r) not in allowed for r in full) else list(full)
        for layer in eff_layers:
            if layer.table != table_id:
                continue
            positions = [index for index, column in enumerate(layer.columns) if column.casefold() in wanted]
            if not positions:
                continue
            seen = frozenset(tuple(item[index] for index in positions) for item in layer.tuples)
            names = [layer.columns[index] for index in positions]
            result = [row for row in result if row_key(typed_cell(source_context, name, row.get(name)) for name in names) in seen]
        return result

    def rows_after_clearing_columns(
        source_context: dict[str, Any],
        columns_to_clear: set[str],
        with_expansion: bool = False,
        other_tables: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        set[str],
    ]:
        """Recompute a table's visible rows after removing only selected columns.

        other_tables: table id -> casefolded column -> the filter rows to put back there (None = no filter), for the filters
        of one-side tables that a row context set and ALLSELECTED must not see."""
        table_id = source_context["id"]
        updated_contexts = [
            dict(context) for context in evaluation_contexts_by_id.values()
        ]
        updated_by_id = {context["id"]: context for context in updated_contexts}
        updated = updated_by_id[table_id]
        existing_column_rows = dict(updated.get("filter_column_rows", {}))
        if _context_shapes(updated):
            clear_columns_from_shapes(updated, columns_to_clear, existing_column_rows)
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
            column: _frozen(indexes)
            for column, indexes in existing_column_rows.items()
            if column.casefold() not in columns_to_clear
        }
        updated["filter_column_rows"] = remaining_column_rows
        prune_cleared_shapes(updated, columns_to_clear)
        updated["filter_column_blank_allowed"] = {
            column: allowed
            for column, allowed in updated.get(
                "filter_column_blank_allowed", {}
            ).items()
            if column.casefold() not in columns_to_clear
        }
        updated["filter_context_complete"] = True
        updated_filter_roots = set(evaluation_filter_ids)
        if with_expansion:  # ALL(column) / ALLSELECTED(column) as a table: filters of the one-side tables do not reach the column (live Power BI)
            for related_id in cleared_by_column_table(table_id):
                related = updated_by_id[related_id]
                for state in ("filter_rows", "filter_table_rows", "filter_shapes", "filter_column_extra"):
                    related.pop(state, None)
                related["filter_column_rows"] = {}
                related["filter_column_blank_allowed"] = {}
                related["filter_context_complete"] = True
                updated_filter_roots.discard(related_id)
        for other_id, replacements in (other_tables or {}).items():
            other = updated_by_id[other_id]
            other_rows = {
                column: rows for column, rows in other.get("filter_column_rows", {}).items()
                if column.casefold() not in replacements
            }
            for folded, outer in replacements.items():
                if outer is not None:
                    other_rows[next(h for h in other["headers"] if h.casefold() == folded)] = frozenset(outer)
            for layer in eff_layers:  # the rows an enclosing iterator walks still narrow this table for ALLSELECTED
                if layer.table != other_id:
                    continue
                allowed = BlankSet(
                    (index for index, base_row in enumerate(other["rows"])
                     if row_key(typed_cell(other, column, base_row.get(column)) for column in layer.columns) in layer.tuples),
                    row_key(None for _column in layer.columns) in layer.tuples,  # the iterated rows list the unknown member
                )
                for column in layer.columns:
                    existing = other_rows.get(column)
                    other_rows[column] = allowed if existing is None else meet_rows(allowed, existing)
            other["filter_column_rows"] = other_rows
            other["filter_context_complete"] = True
            if other_rows:
                other["filter_rows"] = [
                    row for row_index, row in enumerate(other["rows"])
                    if all(row_index in indexes for indexes in other_rows.values())
                ]
                updated_filter_roots.add(other_id)
            else:
                other.pop("filter_rows", None)
                updated_filter_roots.discard(other_id)
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
                ignore_exclusions=cleared_by_column_table(table_id) if with_expansion else (),
            )
        except RelationshipError as exc:
            raise MeasureError(f"Could not apply ALL column filters: {exc}") from exc
        return (
            filtered_rows_by_id[table_id],
            updated_by_id,
            updated_filter_roots,
        )

    def rows_after_restoring_visual_axis() -> tuple[
        dict[str, dict[str, Any]], set[str], dict[str, list[dict[str, Any]]]
    ]:
        """Restore a chart's selected column context without its current category."""
        axis = visual_axis_context
        if axis is None:
            return evaluation_contexts_by_id, set(evaluation_filter_ids), rows_by_table_id
        updated_contexts = [
            dict(context) for context in evaluation_contexts_by_id.values()
        ]
        updated_by_id = {context["id"]: context for context in updated_contexts}
        updated = updated_by_id[axis.table_id]
        if "filter_table_rows" in updated or _context_shapes(updated):
            raise MeasureError(
                "ALLSELECTED chart totals cannot replace an opaque FILTER rowset."
            )
        existing_columns = dict(updated.get("filter_column_rows", {}))
        has_direct_filter_state = (
            axis.table_id in evaluation_filter_ids
            or "filter_rows" in updated
            or bool(existing_columns)
        )
        if has_direct_filter_state and not updated.get(
            "filter_context_complete", False
        ):
            raise MeasureError(
                "ALLSELECTED chart totals need complete per-column filter context."
            )
        matching_column = next(
            (
                column for column in existing_columns
                if column.casefold() == axis.column.casefold()
            ),
            None,
        )
        if matching_column is not None:
            del existing_columns[matching_column]
        if axis.selected_rows is not None:
            existing_columns[axis.column] = axis.selected_rows
        updated["filter_column_rows"] = {
            column: _frozen(indexes)
            for column, indexes in existing_columns.items()
        }

        blank_allowed = dict(updated.get("filter_column_blank_allowed", {}))
        if matching_column is not None:
            blank_allowed.pop(matching_column, None)
        if axis.selected_rows is not None and axis.blank_allowed is not None:
            blank_allowed[axis.column] = axis.blank_allowed
        else:
            blank_allowed.pop(axis.column, None)
        updated["filter_column_blank_allowed"] = blank_allowed
        updated["filter_context_complete"] = True

        updated_filter_roots = set(evaluation_filter_ids)
        if existing_columns:
            updated["filter_rows"] = [
                row
                for row_index, row in enumerate(updated["rows"])
                if all(
                    row_index in indexes
                    for indexes in existing_columns.values()
                )
            ]
            updated_filter_roots.add(axis.table_id)
        else:
            updated.pop("filter_rows", None)
            if axis.table_id not in axis.filter_table_ids:
                updated_filter_roots.discard(axis.table_id)

        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            raise MeasureError(
                f"Could not apply ALLSELECTED chart selection: {exc}"
            ) from exc
        return updated_by_id, updated_filter_roots, filtered_rows_by_id

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
        if "filter_table_rows" in current_source_context and not current_source_context.get("filter_table_unknown", False):
            # FILTER(T, ..) iterates the stored rows only: the generated unknown member is never one of them.
            return False
        if unknown_member_hidden(source_id):
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
        partner_selects_blank = False
        blank_partner_links: set[int] = set()
        for relationship in relationship_definitions:
            # live Power BI (iteration 84, critic): the blank member of a table in a one-to-one relationship is shown while the filter on its
            # partner selects the partner's own blank member (CALCULATE(COUNTROWS(VALUES(U[X])),W[K]<>"k4",W[K]<>"k5") counts it although the
            # orphan row W[k5] is filtered out) and is not shown for the kept orphan rows alone (CALCULATE(COUNTROWS(VALUES(U[K])),W[K]="k5") is BLANK)
            if (
                isinstance(relationship, dict) and relationship.get("is_active") and relationship.get("cardinality") == "one_to_one"
                and source_id in {str(relationship.get("from_table_id", "")), str(relationship.get("to_table_id", ""))}
            ):
                partner_id = next(
                    (str(relationship.get(key)) for key in ("from_table_id", "to_table_id") if str(relationship.get(key)) != source_id), None
                )
                partner = contexts_by_id.get(partner_id) if partner_id is not None else None
                direction = "from_to" if partner_id == str(relationship.get("from_table_id", "")) else "to_from"
                if (
                    partner is not None and partner_id in independent_filter_roots
                    and direction in relationship_filter_directions(relationship)
                    and not eff_transition.get(partner_id)  # a row of an iterator over the partner does show it (SUMX(W, CALCULATE(COUNTROWS(VALUES(U[K])))))
                ):
                    if own_unknown_member_selected(partner):
                        partner_selects_blank = True
                        blank_partner_links.add(id(relationship))
                    elif partner_id in unknown_member_ids:
                        return False
        if source_context["id"] not in context_unknown_members and not partner_selects_blank:
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
            if id(relationship) in blank_partner_links:
                continue  # the partner's filter selects its own blank member: that is what shows this table's blank member
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
            if function == "ALLSELECTED" and eff_active() and (
                shadowed_rows := allselected_rows_for(source_context, output_headers)
            ) is not None:
                output_rows = shadowed_rows
            elif function == "ALLSELECTED":
                output_rows = list(rows_by_table_id[source_context["id"]])
                current_context = evaluation_contexts_by_id.get(
                    source_context["id"], source_context
                )
                if (
                    source_context["id"] in unknown_member_ids
                    and not unknown_member_hidden(source_context["id"])
                    and unknown_member_passes_remaining_filters(
                        current_context,
                        evaluation_contexts_by_id,
                        evaluation_filter_ids,
                    )
                ):
                    output_rows.append({header: None for header in output_headers})
            else:
                output_rows = list(source_context["rows"])
                if function == "ALL" and source_context["id"] in unknown_member_ids:
                    output_rows.append({header: None for header in output_headers})
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
                refuse_one_to_one_blank_reader(source_context["id"], "ALLSELECTED", True)
            allselected_rows = None
            shadowed_rows = (
                allselected_rows_for(source_context, output_headers) if function == "ALLSELECTED" and eff_active() else None
            )
            if function == "ALLSELECTED" and shadowed_rows is None:
                # Power BI: the values of these columns once the filters on the table's other columns are cleared
                # (a filter on one of the columns themselves stays; Facts: CALCULATE(COUNTROWS(ALLSELECTED(Region)),
                # Quantity>3) = 3 but Region="East" gives 1; tools/parity/dax_battery_allselected.json)
                kept_columns = {column.casefold() for column in output_headers}
                cleared_columns = {header.casefold() for header in source_context["headers"]} - kept_columns
                try:
                    allselected_rows = rows_after_clearing_columns(source_context, cleared_columns, True)
                    source_rows, contexts_after_clear, filter_roots_after_clear = allselected_rows
                    # a FILTER table holds only the rows its predicate saw: it never includes the generated blank
                    add_unknown_member = (
                        source_context["id"] in unknown_member_ids
                        and not unknown_member_hidden(source_context["id"])
                        and not _context_shapes(evaluation_contexts_by_id.get(source_context["id"], source_context))
                        and unknown_member_passes_remaining_filters(
                            source_context, contexts_after_clear, filter_roots_after_clear, cleared_columns,
                        )
                    )
                except MeasureError:
                    allselected_rows = None  # a filter context without per-column detail: keep the visible rows
            if shadowed_rows is not None:
                source_rows = shadowed_rows
            elif function == "ALLSELECTED" and allselected_rows is not None:
                own_state = evaluation_contexts_by_id.get(source_context["id"], source_context)
                if (
                    source_context["id"] not in unknown_member_ids
                    and len(source_rows) != len(source_context["rows"])
                    and not own_state.get("filter_column_rows") and not own_state.get("filter_table_rows") and not _context_shapes(own_state)
                    and "filter_rows" not in own_state
                    and any(
                        root != source_context["id"] and not any(
                            isinstance(link, dict) and link.get("is_active") and {link.get("from_table_id"), link.get("to_table_id")} == {root, source_context["id"]}
                            for link in relationship_definitions
                        )
                        for root in evaluation_filter_ids
                    )
                ):  # a filter on a directly related table was measured (saved answer: ALLSELECTED(Dim[Cat]) under Fact[Id]<=7); one two links away was not
                    # live Power BI (ZB): ALLSELECTED(Dim[Prod]) lists all 5 products although a both-way link narrowed the table to 3
                    raise MeasureError("ALLSELECTED over a column that only another table's both-way filter narrows is not supported in the local engine.")
                if add_unknown_member:
                    source_rows.append({header: None for header in source_context["headers"]})
            elif function == "ALLSELECTED":
                source_rows = list(rows_by_table_id[source_context["id"]])
                current_context = evaluation_contexts_by_id.get(
                    source_context["id"], source_context
                )
                if (
                    source_context["id"] in unknown_member_ids
                    and not unknown_member_hidden(source_context["id"])
                    and unknown_member_passes_remaining_filters(
                        current_context,
                        evaluation_contexts_by_id,
                        evaluation_filter_ids,
                    )
                ):
                    source_rows.append({header: None for header in source_context["headers"]})
            else:
                (
                    source_rows,
                    contexts_after_clear,
                    filter_roots_after_clear,
                ) = rows_after_clearing_columns(
                    source_context,
                    {header.casefold() for header in source_context["headers"]},
                    True,
                )
                if function == "ALL" and len(source_rows) != len(source_context["rows"]) and source_context["id"] not in unknown_member_ids:
                    # live Power BI: ALL(column) returns every value of the column, also those a both-way relationship of another
                    # table's filter would hide (ZB: 5 products under Year=2023, not 3).  A table with an unknown member keeps the
                    # older, separately measured rule (Iteration 83: the member and the keys follow the both-way child filters).
                    source_rows = list(source_context["rows"])
                if function == "ALL" and unknown_member_passes_remaining_filters(
                    source_context,
                    contexts_after_clear,
                    filter_roots_after_clear,
                    {header.casefold() for header in source_context["headers"]},
                ):
                    source_rows.append({header: None for header in source_context["headers"]})

            def value_key(value: Any, column: str) -> tuple[str, Any]:
                _reject_power_query_error(value, column, None)
                return cell_key(value)

            output_rows = []
            seen_values: set[tuple[tuple[str, Any], ...]] = set()
            for row in source_rows:
                key = tuple(value_key(row.get(column), column) for column in output_headers)
                if key in seen_values:
                    continue
                seen_values.add(key)
                output_rows.append({column: row.get(column) for column in output_headers})

        if len(arguments) == 1 and arguments[0][0] != "table" and (function != "ALLSELECTED" or allselected_rows is not None or shadowed_rows is not None):
            output_rows = order_distinct_values(source_context, output_headers[0], output_rows)
        value_context = dict(source_context)
        value_context["headers"] = output_headers
        value_context["rows"] = output_rows
        if not (len(arguments) == 1 and arguments[0][0] == "table"):
            value_context["lineage"] = {header: (source_context, header) for header in output_headers}
        return value_context, output_rows

    derived_count = 0
    row_stack: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    selected_iteration_depth = 0  # how many iterations over a SELECTCOLUMNS table are running

    def derived_table(
        headers: list[str],
        rows: list[dict[str, Any]],
        lineage: dict[str, tuple[dict[str, Any], str]] | None = None,
        base_types: dict[str, str] | None = None,
        row_identity: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """A table built by an expression: its rows hold typed DAX values; lineage names the loaded column each came from.

        row_identity: its rows are whole rows of the loaded tables behind its lineage (ADDCOLUMNS, GENERATE, CROSSJOIN keep
        them; SELECTCOLUMNS and SUMMARIZE do not), so a row context on them reaches the tables on the one side too."""
        nonlocal derived_count
        derived_count += 1
        column_types: dict[str, str] = dict(base_types or {})
        for header in headers:
            if header in column_types:
                continue
            sample = next((row[header] for row in rows if row.get(header) is not None), None)
            column_types[header] = (
                "boolean" if isinstance(sample, bool) else "text" if isinstance(sample, str)
                else "date" if isinstance(sample, dax_dates.DaxDateTime) else "decimal_number"
            )
        context = {
            "id": f"derived-{derived_count}", "name": f"Table {derived_count}", "headers": list(headers),
            "rows": rows, "column_types": column_types, "derived": True,
        }
        if lineage is not None:
            context["lineage"] = lineage
        if row_identity:
            context["row_identity"] = True
        return context, rows

    def current_filter(table_id: str, folded: str) -> Any:
        """The row-index set now filtering one column of a table, None when it is not filtered."""
        for column, rows in evaluation_contexts_by_id.get(table_id, {}).get("filter_column_rows", {}).items():
            if column.casefold() == folded:
                return rows
        return None

    def without_eff(thunk: Any) -> Any:
        nonlocal eff_blocked
        saved = eff_blocked
        eff_blocked = True
        try:
            return thunk()
        finally:
            eff_blocked = saved

    def project_layers(layers: tuple[_Shadow, ...], table_id: str, columns: Iterable[str]) -> tuple[_Shadow, ...]:
        dropped = frozenset(column.casefold() for column in columns)
        if not dropped:
            return layers
        kept: list[_Shadow] = []
        for layer in layers:
            projected = layer.projected(dropped) if layer.table == table_id else layer
            if projected is not None:
                kept.append(projected)
        return tuple(kept)

    def shadow_layers_of(context: dict[str, Any], rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], tuple[str, ...], _Shadow]]:
        """One shadow per loaded table the iterated rows' columns come from (nothing for ROW, {..}, computed columns)."""
        lineage = base_lineage(context)
        by_table: dict[str, tuple[dict[str, Any], list[str], list[str]]] = {}
        for header in context["headers"]:
            link = lineage.get(header)
            if link is None:
                continue
            entry = by_table.setdefault(link[0]["id"], (link[0], [], []))
            if link[1] not in entry[1]:
                entry[1].append(link[1])
                entry[2].append(header)
        found = []
        for table_id, (source, columns, headers) in by_table.items():
            def build(headers: list[str] = headers) -> frozenset[tuple[Any, ...]]:
                return frozenset(row_key(typed_row(context, row)[header] for header in headers) for row in rows)
            found.append((table_id, source, tuple(columns), _Shadow(table_id, tuple(columns), build)))
        return found

    def push_shadow(context: dict[str, Any], rows: list[dict[str, Any]], mode: str) -> tuple[Any, ...]:
        """Install (mode "install") or only clear (mode "clear") the shadow of an iterated table; returns what to restore."""
        nonlocal eff_layers, eff_suppressed, eff_blocked
        saved = (eff_layers, eff_suppressed, eff_blocked)
        if mode and not context.get("boolean_filter") and not context.get("no_shadow"):
            eff_blocked = False
            layers, suppressed = eff_layers, dict(eff_suppressed)
            for table_id, _source, columns, layer in shadow_layers_of(context, rows):
                layers = project_layers(layers, table_id, columns)
                suppressed[table_id] = {
                    **suppressed.get(table_id, {}), **{column.casefold(): current_filter(table_id, column.casefold()) for column in columns},
                }
                if mode == "install":
                    layers = (*layers, layer)
            eff_layers, eff_suppressed = layers, suppressed
        return saved

    def pop_shadow(saved: tuple[Any, ...]) -> None:
        nonlocal eff_layers, eff_suppressed, eff_blocked
        eff_layers, eff_suppressed, eff_blocked = saved

    def iterate_rows(
        context: dict[str, Any], rows: list[dict[str, Any]], shadow: str = ""
    ) -> Iterable[tuple[dict[str, Any], dict[str, Any], int]]:
        """Yield each row as a row context while keeping it on the stack EARLIER reads.

        shadow="install": an iterator over a table value filters ALLSELECTED to that table's rows for the loop;
        shadow="clear": CONCATENATEX only removes the outer filters on the columns it iterates."""
        nonlocal selected_iteration_depth
        saved_state = push_shadow(context, rows, shadow)
        selected = bool(context.get("selected_columns"))
        selected_iteration_depth += selected
        try:
            for row_index, row in enumerate(rows, 1):
                frame = (context, row, row_index)
                row_stack.append(frame)
                try:
                    yield frame
                finally:
                    row_stack.pop()
        finally:
            selected_iteration_depth -= selected
            pop_shadow(saved_state)

    def column_in_row_context(frame: tuple[dict[str, Any], dict[str, Any], int], table: str, name: str) -> bool:
        """Whether this row context holds the column (the rules a column reference follows in the innermost row context)."""
        context = frame[0]
        if not context.get("headers"):
            return False  # the empty row context a constant filter is evaluated in
        value_table = resolve_table_context(table) if table else context
        if table and value_table["id"] != context["id"]:
            if context.get("selected_columns"):
                return False  # live Power BI: T[col] is not found among the renamed columns of SELECTCOLUMNS
            lineage = context.get("lineage") or {}
            name = next((
                header for header, (base, column) in lineage.items()
                if base["id"] == value_table["id"] and column.casefold() == name.casefold()
            ), "")
            value_table = context
        if value_table["id"] != context["id"]:
            return False
        return any(str(header).casefold() == name.casefold() for header in context["headers"])

    outer_row_reads = [0]  # how many column reads were answered by an enclosing row context (the walk order of such an iteration is not modelled)

    def enclosing_row_context_for(
        row_context: tuple[dict[str, Any], dict[str, Any], int], table: str, name: str, count: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any], int]:
        """Iteration 88 (live Power BI, nested iterators): a column the innermost row context does not hold is read from the nearest enclosing
        row context that does (SUMX(Facts, SUMX(ROW("a", 1), Facts[Quantity])) is the sum of Quantity per outer row).  The innermost row
        context keeps winning; with no enclosing one the reference is refused as before."""
        if row_context[0].get("boolean_filter") or column_in_row_context(row_context, table, name):
            return row_context
        for frame in reversed(row_stack):
            if frame[1] is row_context[1] or frame[0] is row_context[0] or frame[0].get("boolean_filter"):
                continue  # the implicit iteration of a Boolean filter is no row context of the query
            if column_in_row_context(frame, table, name):
                outer_row_reads[0] += count
                return frame
        return row_context

    def typed_row(context: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
        """A row of a loaded or derived table with every cell as a DAX value."""
        if context.get("derived"):
            return dict(row)
        return {header: typed_cell(context, header, row.get(header)) for header in context["headers"]}

    def base_lineage(context: dict[str, Any]) -> dict[str, tuple[dict[str, Any], str]]:
        existing = context.get("lineage")
        if existing is not None:
            return dict(existing)
        if context.get("derived"):
            return {}
        return {header: (context, header) for header in context["headers"]}

    def row_key(values: Iterable[Any]) -> tuple[Any, ...]:
        return tuple(cell_key(ascii_fold(v) if isinstance(v, str) else v) for v in values)

    profile_cache: dict[tuple[str, str], Any] = {}

    def source_profile(source: dict[str, Any], column: str) -> Any:
        """The dictionary of one loaded column, built once per evaluation."""
        key = (source["id"], column)
        if key not in profile_cache:
            is_text = str(source.get("column_types", {}).get(column, "text")).casefold() == "text"
            profile_cache[key] = dax_iteration_order.Profile(  # the whole loaded column: filters never shrink a dictionary
                [
                    None if raw is None or (not is_text and isinstance(raw, str) and not raw.strip()) else typed_cell(source, column, raw)
                    for raw in (row.get(column) for row in source["rows"])
                ]
            )
        return profile_cache[key]

    def dictionary_ordered_rows(
        table_node: tuple[Any, ...], context: dict[str, Any], rows: list[dict[str, Any]], nodes: list[tuple[Any, ...]]
    ) -> list[dict[str, Any]]:
        """`rows` of `table_node` in the order Power BI walks them for an iterator reading `nodes` (dax_iteration_order).

        Rows come back unchanged whenever the order is not a measured one: that is the order the app always used."""
        plan = dax_iteration_order.plan(table_node, variable_nodes.get)
        header_by_key = {h.casefold(): h for h in context["headers"]}
        read = dax_iteration_order.columns_read(
            nodes,
            lambda name: name in dax_iteration_order.CROSS_TABLE_CALLS,
            lambda name: name in _AGGREGATING_CALLS or name in _TABLE_FUNCTION_ARITY,
            lambda name: name.casefold() in by_name and name.casefold() not in header_by_key,
        ) if plan is not None else None
        if not read:
            return rows
        lineage = base_lineage(context)
        derived = bool(context.get("derived"))
        origin = context.get("order_source")
        # (source table id, source column) -> (source table, column, reader of that column's value for one walked row)
        combination: dict[tuple[str, str], tuple[dict[str, Any], str, Callable[[dict[str, Any]], Any]]] = {}

        def take_header(header: str) -> None:
            base, column = lineage[header]
            combination.setdefault((base["id"], column), (base, column, (
                (lambda row, h=header: row.get(h)) if derived else (lambda row, h=header: typed_cell(context, h, row.get(h)))
            )))

        def take_source_column(name: str) -> bool:
            """A column named in a SELECTCOLUMNS expression: read from the table that was selected from."""
            if origin is None:
                return False
            source_context, source_of = origin
            header = next((h for h in source_context["headers"] if h.casefold() == name.casefold()), None)
            source_lineage = base_lineage(source_context)
            if header is None or header not in source_lineage:
                return False
            base, column = source_lineage[header]
            source_derived = bool(source_context.get("derived"))
            combination.setdefault((base["id"], column), (base, column, (
                lambda row, h=header: (
                    lambda source: source.get(h) if source_derived else typed_cell(source_context, h, source.get(h))
                )(source_of[id(row)])
            )))
            return True

        def take_expression(expression: tuple[Any, ...]) -> bool:
            sources = dax_iteration_order.columns_read([expression], lambda name: name in dax_iteration_order.CROSS_TABLE_CALLS)
            if sources is None:
                return False
            for _table, name in sources:
                header = header_by_key.get(name.casefold())
                if plan.projects:
                    if not take_source_column(name):
                        return False
                elif header is None or header not in lineage:
                    return False
                else:
                    take_header(header)
            return True

        for _table, name in read:
            if (_table, name) == dax_iteration_order.ALL_COLUMNS:
                if plan.computed or plan.projects or sum(1 for every in context["headers"] if every in lineage) > 3:
                    return rows  # only tables of up to three columns were measured (a four-column table stayed in source order)
                for every in context["headers"]:
                    if every in lineage:
                        take_header(every)
                continue
            header = header_by_key.get(name.casefold())
            if header is None:
                return rows
            if header.casefold() in plan.computed:
                if not take_expression(plan.computed[header.casefold()]):
                    return rows
            elif header in lineage and not plan.projects:
                take_header(header)
            else:
                return rows
        if not all(take_expression(expression) for expression in plan.eager):
            return rows
        if plan.dedup:
            for header in context["headers"]:
                if header in lineage:
                    take_header(header)
        if len({key[0] for key in combination}) != 1:
            return rows
        source = next(iter(combination.values()))[0]
        try:
            profiles = {key: source_profile(source, column) for key, (_base, column, _read) in combination.items()}
            in_dictionary_order = dax_iteration_order.grouped(len(source["rows"]), list(profiles.values()), plan.dedup)
            major_first = sorted(combination, key=lambda key: -source["headers"].index(key[1]))  # a later column is the major key

            def walk_key(row: dict[str, Any]) -> tuple[tuple[int, Any], ...]:
                return tuple(profiles[key].key(combination[key][2](row)) for key in major_first)

            return sorted(rows, key=walk_key) if in_dictionary_order else rows
        except (MeasureError, ArithmeticError, ValueError, TypeError, KeyError):  # a row this order cannot place: keep source order
            return rows

    def summarize_related_group(
        context: dict[str, Any], reference: tuple[Any, ...], own_header: str | None
    ) -> tuple[dict[str, Any], str, Callable[[dict[str, Any]], Any]] | None:
        """SUMMARIZE(Fact, Dim[col]): a column of a table on the one side of the summarized table, reached through its
        active relationships (several hops for a snowflake). None when the column is the summarized table's own (or the table
        is unknown, which keeps the old own-column reading). The reader gives the column's value for one typed input row:
        a key with no partner reaches the unknown member, whose columns are BLANK (live Power BI, tests/fixtures_summarize_related.json)."""
        if not reference[1]:
            return None
        try:
            target = resolve_table_context(str(reference[1]))
        except MeasureError:
            return None
        lineage = base_lineage(context)
        if own_header is not None and (lineage.get(own_header) or (None,))[0] is not None and lineage[own_header][0]["id"] == target["id"]:
            return None
        target_column = next((h for h in target["headers"] if h.casefold() == str(reference[2]).casefold()), None)
        if target_column is None:
            return None
        sources: dict[str, dict[str, str]] = {}  # table id -> casefolded column -> header of the input table
        for header, (base, column) in lineage.items():
            sources.setdefault(base["id"], {})[column.casefold()] = header
        if target["id"] in sources:
            return None
        found: list[tuple[str, str, str, str]] | None = None
        for start_id, columns in sources.items():
            queue: list[tuple[str, list[tuple[str, str, str, str]]]] = [(start_id, [])]
            seen = {start_id}
            while queue and found is None:
                node, path = queue.pop(0)
                for one_id, here, there in one_side_links(node):
                    if one_id in seen or one_id not in contexts_by_id or (not path and here.casefold() not in columns):
                        continue
                    seen.add(one_id)
                    step = path + [(node, here, one_id, there)]
                    if one_id == target["id"]:
                        found = step
                        break
                    queue.append((one_id, step))
            if found is not None:
                first_header = columns[found[0][1].casefold()]
                break
        if found is None:
            if own_header is not None and own_header in lineage:  # a column of a table that is not on its one side: not the same-named own column
                raise MeasureError(f"Column '{target['name']}'[{target_column}] is not reachable from the SUMMARIZE table through a many-to-one relationship.")
            return None
        hops = found

        def read(typed: dict[str, Any]) -> Any:
            key = typed[first_header]
            row: dict[str, Any] | None = None
            for position, (_node, _here, one_id, there) in enumerate(hops):
                one_context = contexts_by_id[one_id]
                matches = one_side_value_index(one_context, there).get(cell_key(key))
                if not matches:
                    return None  # the unknown member
                row = one_context["rows"][min(matches)]
                if position + 1 < len(hops):
                    next_here = hops[position + 1][1]
                    key = typed_cell(one_context, next_here, row.get(next_here))
            one_context = contexts_by_id[hops[-1][2]]
            return typed_cell(one_context, target_column, row.get(target_column)) if row is not None else None

        read.key_column = hops[0][1] if len(hops) == 1 and target_column.casefold() == hops[0][3].casefold() else None  # type: ignore[attr-defined]
        return target, target_column, read

    def loaded_table_ids(name: str) -> list[str]:
        return [item["id"] for item in table_names.get(name.casefold(), [])]

    def expression_table_ids(node: Any, seen: set[str] | None = None) -> set[str] | None:
        """The ids of the tables an expression reads, through the measures it names; None when it reads them all (ALL(), ALLSELECTED())."""
        seen = set() if seen is None else seen
        found: set[str] = set()
        stack = [node]
        while stack:
            item = stack.pop()
            if not isinstance(item, tuple) or not item:
                continue
            if item[0] == "table" and len(item) > 1:
                found.update(loaded_table_ids(str(item[1])))  # not a loaded table: a keyword such as Dense
            elif item[0] == "reference" and len(item) > 2:
                if item[1]:
                    found.update(loaded_table_ids(str(item[1])))
                elif str(item[2]).casefold() in by_name:
                    key = str(item[2]).casefold()
                    if key not in seen:
                        seen.add(key)
                        inner = expression_table_ids(parsed[key], seen)
                        if inner is None:
                            return None
                        found |= inner
            elif item[0] == "call" and item[1] in {"ALL", "ALLSELECTED", "REMOVEFILTERS", "ALLNOBLANKROW"} and not item[2]:
                return None
            stack.extend(child for child in item if isinstance(child, tuple))
        return found

    def summarize_reach(table_id: str, allowed: frozenset[int]) -> dict[str, frozenset[int] | None]:
        """The rows of every table on the one side of table_id that the given rows point at; keys with no partner (the unknown member)
        are left out. None for a table all of whose rows are pointed at (nothing to narrow)."""
        reached: dict[str, frozenset[int] | None] = {}
        queue: list[tuple[str, frozenset[int]]] = [(table_id, allowed)]
        while queue:
            current_id, rows_here = queue.pop()
            current = contexts_by_id.get(current_id)
            for one_id, here_column, there_column in one_side_links(current_id):
                one_context = contexts_by_id.get(one_id)
                if current is None or one_context is None or one_id == table_id or one_id in reached:
                    continue
                index = one_side_value_index(one_context, there_column)
                found: set[int] = set()
                for position in rows_here:
                    found |= index.get(cell_key(typed_cell(current, here_column, current["rows"][position].get(here_column))), frozenset())
                reached[one_id] = None if len(found) == len(one_context["rows"]) else frozenset(found)
                queue.append((one_id, frozenset(found)))
        return reached

    def summarize_group_value(
        expression: tuple[Any, ...], group_context: dict[str, Any], group_row: dict[str, Any], source: dict[str, Any], members: list[int],
        key_columns: dict[str, str], unknown_tables: frozenset[str] = frozenset(),
    ) -> Any:
        """An extension column of SUMMARIZE: the group is the set of rows of the summarized table it holds, which also filter the
        tables on that table's one side to the rows they reach (live Power BI: SUMMARIZE(Fact, Fact[Qty], "x", CALCULATE(SUM(Cal[Year])))
        sees only the dates of the group's fact rows)."""
        by_column = transition_filters(group_context, group_row)
        allowed = frozenset(members)
        read = expression_table_ids(expression)  # a table the column never reads needs no narrowing (and may be ambiguous to reach)
        extra: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]] = {}
        if read is None or source["id"] in read or unknown_tables:
            extra[source["id"]] = (source, {column: allowed for column in source["headers"]})
        for one_id, one_rows in summarize_reach(source["id"], allowed).items():
            if one_rows is not None and (read is None or one_id in read):
                one_context = contexts_by_id[one_id]
                extra[one_id] = (one_context, {column: one_rows for column in one_context["headers"]})
        merged: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]] = {}
        for table_id, (base_context, column_rows) in extra.items():
            held = by_column.get(table_id, (base_context, {}))[1]
            merged[table_id] = (base_context, {
                column: (rows & held[column] if column in held else rows) for column, rows in column_rows.items()
            })
        # a group on the key column of the relationship (Dim[Prod] for Fact[Prod]) is the same key as the summarized table's own column;
        # any other column of a table on the one side only reaches the summarized table by the context transition
        own = {t: (c, dict(r)) for t, (c, r) in by_column.items() if t == source["id"]}
        # a group whose one-side column is BLANK is the unknown member: it has no row of that table, only the group's fact rows
        hidden_keys = {t: v for t, v in by_column.items() if t != source["id"] and t not in unknown_tables}
        for header, source_column in key_columns.items():
            key_rows = one_side_value_index(source, source_column).get(cell_key(group_row[header]), frozenset()) if group_row.get(header) is not None else allowed
            own.setdefault(source["id"], (source, {}))[1][source_column] = key_rows
        if not any(t != source["id"] for t in merged) and not unknown_tables:
            merged = {}
        elif source["id"] in merged and source["id"] in own:  # a key column of the group keeps standing as the key
            kept = {c: r for c, r in merged[source["id"]][1].items() if c not in own[source["id"]][1]}
            merged = {**merged, source["id"]: (source, kept)}
        visible = {t: v for t, v in merged.items() if t != source["id"] and t not in hidden_keys}
        hidden = {t: v for t, v in merged.items() if t not in visible}
        return with_column_filters(own, lambda: with_column_filters(hidden_keys, lambda: with_column_filters(
            hidden, lambda: with_column_filters(visible, lambda: evaluate(expression), False), True), True), "keys")

    def is_variant_column_expression(expression: tuple[Any, ...], frame: Any, inherited: Iterable[str]) -> bool:
        """Whether a column added by ADDCOLUMNS / SELECTCOLUMNS is a Variant in Power BI: an IF / SWITCH / COALESCE / IFERROR whose
        branches differ in type (text beside a number, a True/False beside a number ...), or one that reads such a column.  The type
        is that of the branches, not of the values the rows happen to hold (live probes, iteration 85)."""
        if any(str(reference[2]).casefold() in inherited for reference in _iter_reference_nodes(expression) if len(reference) > 2):
            return True
        if expression[0] != "call" or expression[1] not in {"IF", "SWITCH", "COALESCE", "IFERROR"}:
            return False
        try:
            if expression[1] == "COALESCE":  # the category of a COALESCE is that of its first argument; every argument counts here
                merge_branch_categories([iterator_expression_category(argument, frame) for argument in expression[2]], "COALESCE")
            else:
                iterator_expression_category(expression, frame)
        except MeasureError as error:
            return "matching local data types" in str(error) or "same local data type" in str(error)
        return False

    def refuse_variant_aggregation(function: str, context: dict[str, Any], expression: tuple[Any, ...]) -> None:
        """MAXX / MINX / SUMX / AVERAGEX / COUNTX over a Variant column read only its numbers (live Power BI, iteration 85); the local
        engine reads the values of the rows instead, which gave wrong answers, so it refuses."""
        variant = context.get("variant_columns")
        if variant and any(str(reference[2]).casefold() in variant for reference in _iter_reference_nodes(expression) if len(reference) > 2):
            raise MeasureError(f"{function} over a column whose branches have different types is not supported in the local engine.")

    def table_function_rows(argument: tuple[Any, ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        nonlocal eff_touched
        function, arguments = argument[1], argument[2]
        if function == "TABLEOF":
            context = resolve_table_context(arguments[0][1])
            return context, list(rows_by_table_id[context["id"]])
        if function in {"ADDCOLUMNS", "SELECTCOLUMNS"}:
            context, rows = table_argument_value(arguments[0])
            implicit_flags: list[bool] = []
            explicit_taken: set[tuple[str, str]] = set()
            if function == "SELECTCOLUMNS":
                names, expressions, position = [], [], 1
                while position < len(arguments):
                    item = arguments[position]
                    if item[0] == "reference":  # the name can be omitted for a simple column reference
                        names.append(resolve_table(item[1], item[2])[1] if item[1] else item[2])
                        expressions.append(item)
                        implicit_flags.append(True)
                        position += 1
                        continue
                    if position + 1 >= len(arguments):
                        raise MeasureError(
                            f"Function SELECTCOLUMNS expects a column name as argument number {position + 1}. "
                            "The column name can only be omitted for simple column references."
                        )
                    names.append(dax_typed.to_text(evaluate(item)))
                    expressions.append(arguments[position + 1])
                    implicit_flags.append(False)
                    position += 2
            else:
                names = [dax_typed.to_text(evaluate(arguments[i])) for i in range(1, len(arguments), 2)]
                expressions = [arguments[i] for i in range(2, len(arguments), 2)]
                implicit_flags = [False] * len(names)
            add = function == "ADDCOLUMNS"
            taken_names = {h.casefold() for h in context["headers"]} if add else set()
            for position, new_name in enumerate(names):
                bucket = ("implicit" if implicit_flags[position] else "explicit", new_name.casefold())
                if (bucket in explicit_taken) or (add and new_name.casefold() in taken_names):
                    raise MeasureError(f"Function '{function}' cannot add column [{new_name}], as it has the same name as an existing column.")
                explicit_taken.add(bucket)
                taken_names.add(new_name.casefold())
            if not rows:
                refuse_foreign_columns_of_empty_iteration(context, *expressions)
            lineage = base_lineage(context) if add else {}
            headers = (list(context["headers"]) if add else []) + names
            out_rows: list[dict[str, Any]] = []
            source_rows: list[dict[str, Any]] = []
            for frame in iterate_rows(context, rows, "install"):
                source_rows.append(frame[1])
                row = typed_row(context, frame[1]) if add else {}
                for name, expression in zip(names, expressions):
                    try:
                        row[name] = evaluate(expression, frame, allow_text=True)
                    except (MeasureRuntimeError, _HardError) as error:
                        if any(argument is held for held in lazy_column_calls):
                            row[name] = None  # Power BI does not evaluate a column that COUNTROWS never reads
                        elif isinstance(error, _HardError) or isinstance(error, _DivisionError):
                            raise
                        else:
                            raise _HardError(str(error)) from error  # a column that is read is evaluated for every row
                    if not add and expression[0] == "reference":
                        link_context, link_column = resolve_table(expression[1], expression[2]) if expression[1] else (context, expression[2])
                        lineage[name] = (link_context, link_column)
                out_rows.append(row)
            types = dict(context.get("column_types", {})) if add else {}
            variant_columns = set(context.get("variant_columns", ())) if add else set()
            variant_date_columns = set(context.get("variant_date_columns", ())) if add else set()
            column_kinds: dict[str, str | None] = {}
            if rows:
                for name, expression in zip(names, expressions):
                    column_kinds[name] = iterator_body_kind(expression, (context, rows[0], 1))
                    if column_kinds[name] == "numdate":
                        # live Power BI (iteration 87): numbers beside dates make a number column, its dates are plain numbers
                        for out_row in out_rows:
                            if isinstance(out_row.get(name), dax_dates.DaxDateTime):
                                out_row[name] = Decimal(out_row[name])
            static_types = {"variant": "any", "variant_dates": "any", "text": "text", "bool": "boolean", "number": "decimal_number", "numdate": "decimal_number", "date": "date"}
            types.update({name: static_types[kind] for name, kind in column_kinds.items() if kind in static_types})  # the type of the branches, not of the values the rows hold
            selected_context, selected_rows = derived_table(
                headers, out_rows, lineage, {k: v for k, v in types.items() if k in headers}, row_identity=add and not context.get("derived", False) or add and bool(context.get("row_identity")),
            )
            if rows:
                for name, expression in zip(names, expressions):
                    kind = column_kinds[name]
                    if kind in {"variant", "variant_dates"}:
                        variant_columns.add(name.casefold())
                        if kind == "variant_dates":
                            variant_date_columns.add(name.casefold())
                    elif kind != "numdate" and is_variant_column_expression(expression, (context, rows[0], 1), context.get("variant_columns", ())):
                        variant_columns.add(name.casefold())
            if variant_columns:
                selected_context["variant_columns"] = frozenset(variant_columns)
            if variant_date_columns:
                selected_context["variant_date_columns"] = frozenset(variant_date_columns)
            if not add:  # the walk order of a selected column is that of the columns it was computed from
                selected_context["selected_columns"] = True
                selected_context["order_source"] = (context, {id(out): source for out, source in zip(out_rows, source_rows)})
            return selected_context, selected_rows
        if function == "SUMMARIZE":
            context, rows = table_argument_value(arguments[0])
            split = next((i for i, a in enumerate(arguments[1:], 1) if a[0] == "string"), len(arguments))
            group_columns = []
            related_groups: dict[str, tuple[dict[str, Any], str, Callable[[dict[str, Any]], Any]]] = {}  # header -> (one-side table, column, reader)
            for reference in arguments[1:split]:
                if reference[0] != "reference":
                    raise MeasureError("SUMMARIZE groups by column references in the local engine.")
                header_by_key = {h.casefold(): h for h in context["headers"]}
                actual = header_by_key.get(reference[2].casefold())
                related = summarize_related_group(context, reference, actual)
                if related is not None:
                    actual = related[1]
                    if actual.casefold() in {c.casefold() for c in group_columns}:
                        raise MeasureError(f"SUMMARIZE groups by two columns named {actual!r} in the local engine.")
                    related_groups[actual] = related
                if actual is None:
                    raise MeasureError(f"Column {reference[2]!r} does not exist in the SUMMARIZE table.")
                group_columns.append(actual)
            names = [dax_typed.to_text(evaluate(arguments[i])) for i in range(split, len(arguments), 2)]
            expressions = [arguments[i] for i in range(split + 1, len(arguments), 2)]
            taken_names = {column.casefold() for column in group_columns}
            for name in names:
                if name.casefold() in taken_names:  # a static error in Power BI, raised even when the rows are never read
                    raise MeasureError(f"Function 'SUMMARIZE' cannot add column [{name}] since it already exists.")
                taken_names.add(name.casefold())
            full_lineage = base_lineage(context)
            groups: dict[tuple[Any, ...], dict[str, Any]] = {}
            source_base = contexts_by_id.get(context["id"]) if not context.get("derived") else None
            source_positions = {id(r): i for i, r in enumerate(source_base["rows"])} if source_base is not None else {}
            group_members: dict[tuple[Any, ...], list[int]] = {}  # group -> rows of the summarized loaded table in it
            for row in rows:
                typed = typed_row(context, row)
                if related_groups:
                    typed = {**typed, **{c: group[2](typed) for c, group in related_groups.items()}}
                key = row_key(typed[c] for c in group_columns)
                groups.setdefault(key, {c: typed[c] for c in group_columns})
                if id(row) in source_positions:
                    group_members.setdefault(key, []).append(source_positions[id(row)])
            group_key_of = list(groups)
            lineage = {c: full_lineage[c] for c in group_columns if c in full_lineage}
            lineage.update({c: (group[0], group[1]) for c, group in related_groups.items()})
            group_types = {c: context.get("column_types", {}).get(c, "text") for c in group_columns}
            group_types.update({c: group[0].get("column_types", {}).get(group[1], "text") for c, group in related_groups.items()})
            group_context, group_rows = derived_table(list(group_columns), list(groups.values()), lineage, group_types)
            out_rows = []
            saved_shadow, saved_touched = push_shadow(context, rows, "install"), eff_touched  # SUMMARIZE's input table is the shadow
            try:
                for group_position, group_row in enumerate(group_rows):
                    row = dict(group_row)
                    eff_touched = frozenset()
                    members = group_members.get(group_key_of[group_position]) if source_base is not None else None
                    for name, expression in zip(names, expressions):
                        if members:
                            row[name] = summarize_group_value(
                                expression, group_context, group_row, source_base, members,
                                {c: g[2].key_column for c, g in related_groups.items() if g[2].key_column},  # type: ignore[attr-defined]
                                frozenset(g[0]["id"] for c, g in related_groups.items() if group_row.get(c) is None),
                            )
                        else:
                            row[name] = evaluate_with_context_transition(expression, group_context, group_row, keys=True)
                    out_rows.append(row)
            finally:
                pop_shadow(saved_shadow)
                eff_touched = saved_touched
            return derived_table(list(group_columns) + names, out_rows, lineage, group_types)
        if function == "TOPN":
            count = Decimal(dax_typed.whole(in_row_expression(lambda: evaluate(arguments[0])), "TOPN"))
            context, rows = table_argument_value(arguments[1])
            keys_spec = []
            index = 2
            while index < len(arguments):
                descending = True
                expression = arguments[index]
                index += 1
                if index < len(arguments):
                    order = arguments[index]
                    if order[0] == "unary" and order[2][0] == "number":
                        raise MeasureError("Unexpected value for the ORDER argument. Use 0/FALSE/DESC for descending or 1/TRUE/ASC for ascending.")
                    if order[0] == "table" and str(order[1]).upper() in {"ASC", "DESC"}:
                        descending = str(order[1]).upper() == "DESC"
                        index += 1
                    elif order[0] in {"number", "boolean"}:
                        if order[1] not in (0, 1):
                            raise MeasureError("Unexpected value for the ORDER argument. Use 0/FALSE/DESC for descending or 1/TRUE/ASC for ascending.")
                        descending = order[1] == 0 or order[1] is False  # 0 / FALSE sort descending
                        index += 1
                keys_spec.append((expression, descending))
            if not rows:
                refuse_foreign_columns_of_empty_iteration(context, *(expression for expression, _descending in keys_spec))
            if count <= 0 or not rows:
                return context, []
            if not keys_spec:  # no order expression: the first n rows, no ties
                return context, list(rows[: int(count.to_integral_value(rounding=ROUND_FLOOR))])
            walk_nodes = topn_walk_nodes.get(id(argument))
            limit = int(count.to_integral_value(rounding=ROUND_FLOOR))

            def score_rows(source_rows: list[dict[str, Any]]) -> list[tuple[list[Any], dict[str, Any]]]:
                found = []
                outer_reads_before = outer_row_reads[0]
                for frame in iterate_rows(context, source_rows, "install"):
                    keys = []
                    for expression, descending in keys_spec:
                        value = in_row_expression(lambda expression=expression, frame=frame: evaluate(expression, frame, allow_text=True))
                        keys.append(value)
                    found.append((keys, frame[1]))
                if outer_row_reads[0] != outer_reads_before:
                    raise MeasureError("The tie order of a TOPN whose ORDER BY reads an enclosing row context is not modelled in the local engine.")
                return found

            def sort_scored(found: list[tuple[list[Any], dict[str, Any]]]) -> list[tuple[list[Any], dict[str, Any]]]:
                ranked = list(found)
                for position in range(len(keys_spec) - 1, -1, -1):
                    sample = next((item[0][position] for item in found if item[0][position] is not None), None)
                    blank = dax_typed._blank_like(sample) if sample is not None else Decimal(0)
                    ranked.sort(
                        # live Power BI (iteration 88): a BLANK ranks below the zero (or the empty text) it compares equal to
                        key=lambda item, p=position, blank=blank: (column_order_key(blank if item[0][p] is None else item[0][p]), item[0][p] is not None),
                        reverse=keys_spec[position][1],
                    )
                return ranked

            scored = score_rows(rows)
            ordered = sort_scored(scored)
            if walk_nodes is not None and not evaluation_filter_ids and (limit >= len(scored) or row_key(ordered[limit - 1][0]) != row_key(ordered[limit][0])):
                # consumed by CONCATENATEX with nothing tied at the cut: the source is walked in dictionary order over the columns
                # read and the kept rows come back as the array of Power BI's heap (a tie at the cut is not modelled: that keeps
                # the sorted answer over the source order; under a CALCULATE filter the heap order was not measured either)
                walked = dictionary_ordered_rows(arguments[1], context, rows, [*walk_nodes, *(expression for expression, _d in keys_spec)])
                scored = score_rows(walked)
                ordered = sort_scored(scored)
                if limit >= len(scored):
                    return dict(context), [item[1] for item in scored]  # nothing is cut: the table comes back in walk order
                column_keys = [blank_aware_keys([item[0][p] for item in scored]) for p in range(len(keys_spec))]

                def beats(a: int, b: int) -> bool:
                    for position, (_expression, descending) in enumerate(keys_spec):
                        left, right = column_keys[position][a], column_keys[position][b]
                        if left != right:
                            return (left > right) == descending
                    return False

                return dict(context), [scored[index][1] for index in dax_iteration_order.heap_top(limit, range(len(scored)), beats)]
            kept = ordered[:limit]
            if kept and len(ordered) > limit:
                boundary = row_key(v for v in ordered[limit - 1][0])
                for item in ordered[limit:]:
                    if row_key(v for v in item[0]) == boundary:
                        kept.append(item)
                    else:
                        break
            result_context = dict(context)
            return result_context, [item[1] for item in kept]
        if function in {"UNION", "EXCEPT", "INTERSECT", "CROSSJOIN"}:
            tables = [table_argument_value(a) for a in arguments]
            typed_tables = [(c, [typed_row(c, r) for r in rows]) for c, rows in tables]
            first_context, first_rows = typed_tables[0]
            headers = list(first_context["headers"])
            if function == "CROSSJOIN":
                merged_headers = list(headers)
                lineage = base_lineage(first_context)
                output = first_rows
                for context, rows in typed_tables[1:]:
                    merged_headers += [h for h in context["headers"]]
                    lineage.update(base_lineage(context))
                    output = [{**left, **right} for right in rows for left in output]  # Power BI: the FIRST table varies fastest
                if len({h.casefold() for h in merged_headers}) != len(merged_headers):
                    raise MeasureError("CROSSJOIN does not allow two columns with the same name.")
                return derived_table(merged_headers, output, lineage, {
                    k: v for c, _ in typed_tables for k, v in c.get("column_types", {}).items()
                }, row_identity=all(not c.get("derived") or c.get("row_identity") or c.get("lineage") is None for c, _ in typed_tables))
            def column_kind(context: dict[str, Any], header: str) -> str:
                kind = str(context.get("column_types", {}).get(header, "text")).casefold()
                return "number" if kind in _COLUMN_NUMBER_TYPES else kind
            projected = []
            for context, rows in typed_tables:
                other = list(context["headers"])
                if len(other) != len(headers):
                    raise MeasureError(f"{function} needs tables with the same number of columns.")
                for first_header, other_header in zip(headers, other):
                    if function != "UNION" and column_kind(first_context, first_header) != column_kind(context, other_header) and rows and first_rows:
                        raise MeasureError(f"{function} needs columns of the same data type.")
                projected.append([{h: row[o] for h, o in zip(headers, other)} for row in rows])
            if function == "UNION":
                output = [row for rows in projected for row in rows]
                def lineage_ids(context: dict[str, Any]) -> dict[str, tuple[Any, str]]:  # the same source column, whatever copy of its table holds it
                    return {header: (table["id"], column.casefold()) for header, (table, column) in base_lineage(context).items()}
                same_lineage = all(lineage_ids(c) == lineage_ids(first_context) for c, _ in typed_tables)
                return derived_table(headers, output, base_lineage(first_context) if same_lineage else None, first_context.get("column_types"))
            right_keys = {row_key(row[h] for h in headers) for row in projected[1]}
            keep = (lambda key: key not in right_keys) if function == "EXCEPT" else (lambda key: key in right_keys)
            output = [row for row in projected[0] if keep(row_key(row[h] for h in headers))]
            return derived_table(headers, output, base_lineage(first_context), first_context.get("column_types"))
        if function == "CALCULATETABLE":
            captured: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
            capture_node = ("call", "CALCULATE", (("tablecapture", arguments[0], captured),) + tuple(arguments[1:]))
            quirk = arguments[0][0] == "call" and arguments[0][1] == "ALLEXCEPT"
            if quirk:
                counting_rows.append(True)
            try:
                if row_stack:  # inside a row context CALCULATETABLE transitions it, like CALCULATE
                    with_column_filters(all_row_context_filters(None), lambda: evaluate(capture_node))
                else:
                    evaluate(capture_node)
            finally:
                if quirk:
                    counting_rows.pop()
            return captured[-1]
        if function in {"INDEX", "OFFSET", "WINDOW"}:
            return window_table(function, arguments)
        if function in _NEW_TABLE_FUNCTIONS:
            return new_table_function(function, arguments)
        raise MeasureError(f"{function} is not supported by the local DAX engine.")

    group_stack: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    counting_rows: list[bool] = []  # non-empty while COUNTROWS evaluates its table argument
    direct_counting_table_vars: list[str] = []
    _COLUMN_NUMBER_TYPES = {"whole_number", "decimal_number", "decimal", "fixed_decimal", "currency", "number", "int64", "double"}

    def order_arguments(arguments: tuple[tuple[Any, ...], ...]) -> list[tuple[Any, bool]]:
        """(expression, descending) pairs from a trailing orderBy list; DESC is the default, as in TOPN."""
        spec: list[tuple[Any, bool]] = []
        index = 0
        while index < len(arguments):
            descending = True
            expression = arguments[index]
            index += 1
            if index < len(arguments):
                order = arguments[index]
                if order[0] == "table" and str(order[1]).upper() in {"ASC", "DESC"}:
                    descending = str(order[1]).upper() == "DESC"
                    index += 1
                elif order[0] in {"number", "boolean"}:
                    if order[1] not in (0, 1):
                        raise MeasureError("Unexpected value for the ORDER argument. Use 0/FALSE/DESC for descending or 1/TRUE/ASC for ascending.")
                    descending = order[1] == 0 or order[1] is False
                    index += 1
            spec.append((expression, descending))
        return spec

    def sorted_table(source: tuple[Any, ...], spec_arguments: tuple[tuple[Any, ...], ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Every row of the table in the order TOPN would rank them."""
        _context, rows = table_argument_value(source)
        if not rows:
            return _context, []
        return table_function_value(("call", "TOPN", (("number", Decimal(len(rows))), source, *spec_arguments)))

    def group_columns_of(context: dict[str, Any], references: list[tuple[Any, ...]], label: str) -> list[str]:
        header_by_key = {h.casefold(): h for h in context["headers"]}
        actual_columns = []
        for reference in references:
            actual = header_by_key.get(reference[2].casefold())
            if actual is None:
                raise MeasureError(f"Column {reference[2]!r} does not exist in the {label} table.")
            if actual in actual_columns:
                raise MeasureError(f"The column '{actual}' was specified more than once in the '{label}' function.")
            actual_columns.append(actual)
        return actual_columns

    def summarize_columns(arguments: tuple[tuple[Any, ...], ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        references: list[tuple[Any, ...]] = []
        filter_nodes: list[tuple[Any, ...]] = []
        names: list[str] = []
        expressions: list[tuple[Any, ...]] = []
        index = 0
        while index < len(arguments):
            argument = arguments[index]
            if argument[0] == "reference" and argument[1] and not names and not filter_nodes:
                references.append(argument)
                index += 1
            elif argument[0] == "string":
                if index + 1 >= len(arguments):
                    raise MeasureError("SUMMARIZECOLUMNS needs an expression after each column name.")
                names.append(str(argument[1]))
                expressions.append(arguments[index + 1])
                index += 2
            elif not names and _is_general_table_filter(argument):
                filter_nodes.append(argument)
                index += 1
            else:
                raise MeasureError("SUMMARIZECOLUMNS takes group-by columns, then filter tables, then name and expression pairs.")
        resolved = [resolve_table(reference[1], reference[2]) for reference in references]
        headers = [column for _context, column in resolved]
        if len({h.casefold() for h in headers}) != len(headers):
            raise MeasureError("A column was specified more than once in the 'SUMMARIZECOLUMNS' function.")
        taken = {h.casefold() for h in headers}
        for name in names:
            if name.casefold() in taken:
                raise MeasureError(f"Function 'SUMMARIZECOLUMNS' cannot add column [{name}], as it has the same name with an existing column.")
            taken.add(name.casefold())
        ignored: list[bool] = []
        stripped: list[tuple[Any, ...]] = []
        for expression in expressions:
            wrapper = expression[0] == "call" and expression[1] in {"IGNORE", "NONVISUAL"}
            ignored.append(wrapper and expression[1] == "IGNORE")
            stripped.append(expression[2][0] if wrapper else expression)
        if not headers and not names:
            raise MeasureError("SUMMARIZECOLUMNS needs a group-by column or a name and expression.")
        if len({context["id"] for context, _column in resolved}) > 1 and not names:
            raise MeasureError("SUMMARIZECOLUMNS over columns of several tables needs at least one expression in the local engine.")
        added: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]]]] = {}
        for node in filter_nodes:  # filter tables are evaluated in the outer filter context
            for table_id, (context, column_rows, shapes) in general_table_filter_sets(node).items():
                _context, target, target_shapes = added.setdefault(table_id, (context, {}, []))
                overlap = {column for column in column_rows if column in target}
                for column, allowed in column_rows.items():
                    target[column] = allowed if column not in target else allowed & target[column]
                if overlap:  # two filters on the same column intersect: the rows no longer form one clean shape
                    for shape in (*target_shapes, *shapes):
                        if overlap & set(shape["columns"]):
                            shape["dirty"] = True
                target_shapes.extend(shapes)

        def compute() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            by_table: dict[str, tuple[dict[str, Any], list[str]]] = {}
            for context, column in resolved:
                by_table.setdefault(context["id"], (context, []))[1].append(column)
            combos: list[dict[str, Any]] = [{}]
            for table_id, (context, columns) in by_table.items():
                seen: dict[tuple[Any, ...], dict[str, Any]] = {}
                for raw in rows_by_table_id[table_id]:
                    values = {column: typed_cell(context, column, raw.get(column)) for column in columns}
                    seen.setdefault(row_key(values[column] for column in columns), values)
                if (  # the blank member is a group of its own while it is visible
                    table_id in unknown_member_ids and not unknown_member_hidden(table_id)
                    and unknown_member_passes_remaining_filters(
                        evaluation_contexts_by_id.get(table_id, context), evaluation_contexts_by_id, evaluation_filter_ids)
                ):
                    seen.setdefault(row_key([None] * len(columns)), {column: None for column in columns})
                combos = [{**left, **right} for left in combos for right in seen.values()]
            lineage = {column: (context, column) for context, column in resolved}
            types = {column: context.get("column_types", {}).get(column, "text") for context, column in resolved}

            def order_key(row: dict[str, Any]) -> tuple[Any, ...]:
                return tuple((value is not None, column_order_key(value) if value is not None else 0) for value in (row[h] for h in headers))
            combos.sort(key=order_key)
            group_context, group_rows = derived_table(list(headers), combos, lineage, types)
            output = []
            for group_row in group_rows:
                row = dict(group_row)
                for name, expression in zip(names, stripped):
                    row[name] = evaluate_with_context_transition(expression, group_context, group_row)
                counted = [row[name] for name, skip in zip(names, ignored) if not skip]
                if names and not all(skip for skip in ignored) and all(value is None for value in counted):
                    continue  # a row whose expressions are all blank is dropped
                output.append(row)
            return derived_table(list(headers) + names, output, lineage, types)

        return with_column_filters(added, compute) if added else compute()

    def group_by(arguments: tuple[tuple[Any, ...], ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        context, rows = table_argument_value(arguments[0])
        split = next((i for i, a in enumerate(arguments[1:], 1) if a[0] == "string"), len(arguments))
        references = list(arguments[1:split])
        if any(reference[0] != "reference" for reference in references):
            raise MeasureError("GROUPBY groups by column references.")
        columns = group_columns_of(context, references, "GROUPBY")
        if (len(arguments) - split) % 2:
            raise MeasureError("GROUPBY needs an expression after each column name.")
        names = [str(arguments[i][1]) for i in range(split, len(arguments), 2)]
        expressions = [arguments[i] for i in range(split + 1, len(arguments), 2)]
        iterators = _ALL_ITERATORS | {"PRODUCTX"}
        for expression in expressions:
            if not (
                expression[0] == "call" and expression[1] in iterators and expression[2]
                and expression[2][0][:2] == ("call", "CURRENTGROUP")
            ):
                raise MeasureError("Function 'GROUPBY' scalar expressions have to be Aggregation functions over CurrentGroup().")
        if len({n.casefold() for n in names} | {c.casefold() for c in columns}) != len(names) + len(columns):
            raise MeasureError("Function 'GROUPBY' cannot add a column with the same name as an existing column.")
        groups: dict[tuple[Any, ...], tuple[dict[str, Any], list[dict[str, Any]]]] = {}
        for row in rows:
            typed = typed_row(context, row)
            key = row_key(typed[column] for column in columns)
            groups.setdefault(key, ({column: typed[column] for column in columns}, []))[1].append(row)
        lineage_all = base_lineage(context)
        lineage = {column: lineage_all[column] for column in columns if column in lineage_all}
        output = []
        for values, group_rows in groups.values():
            row = dict(values)
            group_stack.append((context, group_rows))
            try:
                for name, expression in zip(names, expressions):
                    row[name] = evaluate(expression, None, allow_text=True)
            finally:
                group_stack.pop()
            output.append(row)
        return derived_table(columns + names, output, lineage, {c: context.get("column_types", {}).get(c, "text") for c in columns})

    def treat_as(arguments: tuple[tuple[Any, ...], ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        context, rows = table_argument_value(arguments[0])
        if any(reference[0] != "reference" or not reference[1] for reference in arguments[1:]):
            raise MeasureError("TREATAS needs qualified target columns.")
        targets = [resolve_table(reference[1], reference[2]) for reference in arguments[1:]]
        if len(targets) != len(context["headers"]):
            raise MeasureError("The number of columns in the TREATAS table must match the number of target columns.")
        headers = [column for _context, column in targets]

        def coerce(target_context: dict[str, Any], column: str, value: Any) -> Any:
            if value is None:
                return None
            kind = str(target_context.get("column_types", {}).get(column, "text")).casefold()
            if kind in _COLUMN_NUMBER_TYPES:
                number = dax_typed.to_number(value) if not isinstance(value, str) else dax_typed.text_to_number(value)
                return number.quantize(Decimal(1), rounding=ROUND_HALF_UP) if kind in {"whole_number", "int64"} else number
            if kind == "boolean":
                return dax_typed.to_boolean(value)
            if kind in {"date", "datetime"}:
                return value
            return value if isinstance(value, str) else dax_typed.to_text(value)

        existing: dict[str, set[tuple[Any, ...]]] = {}
        output: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for row in rows:
            typed = typed_row(context, row)
            try:
                values = [coerce(tc, column, typed[source]) for (tc, column), source in zip(targets, context["headers"])]
            except MeasureRuntimeError:
                continue  # a value that cannot become the column's type matches nothing
            ok = True
            for table_id in {tc["id"] for tc, _column in targets}:
                tc = next(t for t, _c in targets if t["id"] == table_id)
                pairs = [(i, column) for i, (t, column) in enumerate(targets) if t["id"] == table_id]
                if table_id not in existing:
                    existing[table_id] = set()
                key_set = existing.setdefault(table_id + "|" + ",".join(c for _i, c in pairs), set())
                if not key_set:
                    for base_row in tc["rows"]:
                        key_set.add(row_key(typed_cell(tc, column, base_row.get(column)) for _i, column in pairs))
                if row_key(values[i] for i, _column in pairs) not in key_set and not (
                    table_id in unknown_member_ids and all(values[i] is None for i, _column in pairs)
                ):  # BLANK() in the list names the generated blank member of a table that has one
                    ok = False
            key = row_key(values)
            if ok and key not in seen:
                seen.add(key)
                output.append(dict(zip(headers, values)))
        lineage = {column: (tc, column) for tc, column in targets}
        types = {column: tc.get("column_types", {}).get(column, "text") for tc, column in targets}
        return derived_table(headers, output, lineage, types)

    def natural_join(arguments: tuple[tuple[Any, ...], ...], outer: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        left_context, left_rows = table_argument_value(arguments[0])
        right_context, right_rows = table_argument_value(arguments[1])
        right_by_key = {h.casefold(): h for h in right_context["headers"]}
        common = [(h, right_by_key[h.casefold()]) for h in left_context["headers"] if h.casefold() in right_by_key]
        if not common:
            raise MeasureError("No common join columns detected. The natural join functions need at least one common join column.")
        extra = [h for h in right_context["headers"] if h.casefold() not in {l.casefold() for l, _r in common}]
        index: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for row in right_rows:
            typed = typed_row(right_context, row)
            index.setdefault(row_key(typed[r] for _l, r in common), []).append(typed)
        output = []
        for row in left_rows:
            typed = typed_row(left_context, row)
            matches = index.get(row_key(typed[l] for l, _r in common), [])
            if matches:
                output.extend({**typed, **{h: match[h] for h in extra}} for match in matches)
            elif outer:
                output.append({**typed, **{h: None for h in extra}})
        lineage = {**base_lineage(right_context), **base_lineage(left_context)}
        types = {**right_context.get("column_types", {}), **left_context.get("column_types", {})}
        return derived_table(list(left_context["headers"]) + extra, output, lineage, types)

    def generate(arguments: tuple[tuple[Any, ...], ...], keep_empty: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        left_context, left_rows = table_argument_value(arguments[0])
        output: list[dict[str, Any]] = []
        right_headers: list[str] | None = None
        right_types: dict[str, str] = {}
        right_lineage: dict[str, tuple[dict[str, Any], str]] = {}
        pending: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for frame in iterate_rows(left_context, left_rows, "install"):
            right_context, right_rows = table_argument_value(arguments[1])
            if right_headers is None:
                right_headers = list(right_context["headers"])
                clash = {h.casefold() for h in right_headers} & {h.casefold() for h in left_context["headers"]}
                if clash:
                    raise MeasureError(f"Function {'GENERATEALL' if keep_empty else 'GENERATE'} does not allow two columns with the same name.")
                right_types = dict(right_context.get("column_types", {}))
                right_lineage = base_lineage(right_context)
            pending.append((typed_row(left_context, frame[1]), [typed_row(right_context, r) for r in right_rows]))
        if right_headers is None:
            right_context, _rows = table_argument_value(arguments[1])
            right_headers = list(right_context["headers"])
            right_types = dict(right_context.get("column_types", {}))
            right_lineage = base_lineage(right_context)
        for left, matches in pending:
            if matches:
                output.extend({**left, **{h: match[h] for h in right_headers}} for match in matches)
            elif keep_empty:
                output.append({**left, **{h: None for h in right_headers}})
        lineage = {**right_lineage, **base_lineage(left_context)}
        return derived_table(list(left_context["headers"]) + right_headers, output, lineage, {**right_types, **left_context.get("column_types", {})},
                             row_identity=(not left_context.get("derived") or bool(left_context.get("row_identity"))))

    def new_table_function(function: str, arguments: tuple[tuple[Any, ...], ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if function == "SUMMARIZECOLUMNS":
            return summarize_columns(arguments)
        if function == "GROUPBY":
            return group_by(arguments)
        if function == "TREATAS":
            return treat_as(arguments)
        if function in {"NATURALINNERJOIN", "NATURALLEFTOUTERJOIN"}:
            return natural_join(arguments, function == "NATURALLEFTOUTERJOIN")
        if function in {"GENERATE", "GENERATEALL"}:
            return generate(arguments, function == "GENERATEALL")
        if function == "SAMPLE":
            size_value = evaluate(arguments[0])
            if size_value is None:
                return table_argument_value(arguments[1])[0], []
            size = int(dax_typed.to_number(size_value).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            if size < 0:
                raise MeasureRuntimeError("SAMPLE function can only be used with a non-negative sample size argument.")
            context, ordered = sorted_table(arguments[1], tuple(arguments[2:]))
            if size == 0 or not ordered:
                return context, []
            if size >= len(ordered):
                return context, list(ordered)
            if size == 1:
                return context, [ordered[0]]
            step = Decimal(len(ordered) - 1) / Decimal(size - 1)
            positions = [int((step * i).quantize(Decimal(1), rounding=ROUND_HALF_UP)) for i in range(size)]
            return context, [ordered[position] for position in positions]
        if function == "TOPNSKIP":
            count = dax_typed.whole(evaluate(arguments[0]), "TOPNSKIP")
            skip = max(0, dax_typed.whole(evaluate(arguments[1]), "TOPNSKIP"))
            context, rows = table_argument_value(arguments[2])
            if count <= 0 or not rows:
                return context, []
            _ranked_context, ranked = table_function_value(
                ("call", "TOPN", (("number", Decimal(count + skip)), arguments[2], *arguments[3:]))
            )
            return context, ranked[skip:]
        if function == "FILTERS":
            reference = arguments[0]
            if reference[0] != "reference":
                raise MeasureError("FILTERS needs a column.")
            context, actual = resolve_table(reference[1], reference[2])
            allowed = evaluation_contexts_by_id.get(context["id"], context).get("filter_column_rows", {}).get(actual)
            seen_values: set[Any] = set()
            value_rows = []
            for row_index, row in enumerate(context["rows"]):
                if allowed is not None and row_index not in allowed:
                    continue
                key = cell_key(ascii_fold(row.get(actual)) if isinstance(row.get(actual), str) else row.get(actual))
                if key not in seen_values:
                    seen_values.add(key)
                    value_rows.append({actual: row.get(actual)})
            single = dict(context)
            single["headers"] = [actual]
            single["lineage"] = {actual: (context, actual)}
            return single, value_rows
        if function == "CALENDAR":
            bounds = []
            for argument in arguments:
                value = evaluate(argument, None, allow_text=True)
                if value is None:
                    raise MeasureRuntimeError("The start date or end date in Calendar function can not be Blank value.")
                if isinstance(value, str):
                    value = dax_dates.parse_date_text(value)
                bounds.append(int(dax_typed.to_number(value).to_integral_value(rounding=ROUND_FLOOR)))
            if bounds[0] > bounds[1]:
                raise MeasureRuntimeError("The start date in Calendar function can not be later than the end date.")
            if bounds[1] - bounds[0] > 3_700_000:
                raise MeasureRuntimeError("The Calendar function range is too large.")
            return derived_table(["Date"], [{"Date": dax_dates.DaxDateTime(Decimal(day))} for day in range(bounds[0], bounds[1] + 1)], None, {"Date": "date"})
        if function == "DATATABLE":
            last = arguments[-1]
            if last[0] != "tableconstructor" or (len(arguments) - 1) % 2:
                raise MeasureError("DATATABLE needs column names and types followed by a table of rows.")
            names = [str(arguments[i][1]) for i in range(0, len(arguments) - 1, 2)]
            kinds = []
            for i in range(1, len(arguments) - 1, 2):
                if arguments[i][0] != "table" or str(arguments[i][1]).upper() not in {"INTEGER", "DOUBLE", "STRING", "BOOLEAN", "CURRENCY", "DATETIME"}:
                    raise MeasureError("DATATABLE column types are INTEGER, DOUBLE, STRING, BOOLEAN, CURRENCY and DATETIME.")
                kinds.append(str(arguments[i][1]).upper())
            records = []
            for item in last[1]:
                members = item[1] if item[0] == "tableconstructor" else (item,)
                if len(members) != len(names):
                    raise MeasureError("Every DATATABLE row needs a value for each column.")
                def datatable_value(kind: str, value: Any) -> Any:
                    if kind == "DATETIME" and isinstance(value, str):
                        return dax_dates.parse_date_text(value)
                    return convert_value(value, kind)

                records.append({
                    name: datatable_value(kind, evaluate(member, None, allow_text=True))
                    for name, kind, member in zip(names, kinds, members)
                })
            types = {n: {"INTEGER": "whole_number", "DOUBLE": "decimal_number", "STRING": "text", "BOOLEAN": "boolean", "CURRENCY": "decimal_number", "DATETIME": "date"}[k] for n, k in zip(names, kinds)}
            return derived_table(names, records, None, types)
        raise MeasureError(f"{function} is not supported by the local DAX engine.")

    def blank_aware_keys(values: list[Any]) -> list[tuple[Any, int]]:
        """Sort keys in which BLANK sits just below the zero of the column's type (between the negatives and 0)."""
        classes = {2 if isinstance(v, bool) else 1 if isinstance(v, str) else 0 for v in values if v is not None}
        if len(classes) > 1:
            # keys of different types (Power BI, tools/parity/dax_battery_round5.json): numbers and dates first, with BLANK
            # counted as 0 among them, then text, then Booleans
            return [(0, Decimal(0), 0) if v is None else (2 if isinstance(v, bool) else 1 if isinstance(v, str) else 0, column_order_key(v), 1) for v in values]
        sample = next((v for v in values if v is not None), None)
        zero_key = column_order_key(dax_typed._blank_like(sample)) if sample is not None else 0
        return [(zero_key, 0) if v is None else (column_order_key(v), 1) for v in values]

    class _Window:
        """The relation, its ordering and partitions, and the current rows of one INDEX / OFFSET / WINDOW / RANK call."""

    def relation_may_have_duplicates(node: tuple[Any, ...]) -> bool:
        """Power BI refuses a window relation that keeps whole rows of a table (no column set to deduplicate it)."""
        table_names = {str(ctx["name"]).upper() for ctx in contexts_by_id.values()}
        if node[0] == "table":
            return str(node[1]).upper() in table_names
        if node[0] == "table_call":
            return node[1] in {"VALUES"} and node[2][0] == "table" and str(node[2][1]).upper() in table_names
        if node[0] != "call":
            return False
        function, arguments = node[1], node[2]
        if function in {"ALL", "ALLNOBLANKROW", "ALLSELECTED"}:
            return len(arguments) == 1 and arguments[0][0] == "table" and str(arguments[0][1]).upper() in table_names
        if function in {"FILTER", "CALCULATETABLE", "TOPN", "ADDCOLUMNS", "SELECTCOLUMNS", "EXCEPT", "INTERSECT"}:
            source = arguments[1] if function == "TOPN" and len(arguments) > 1 else arguments[0] if arguments else None
            return source is not None and relation_may_have_duplicates(source)
        return function == "UNION"

    def window_setup(arguments: tuple[tuple[Any, ...], ...], function: str) -> Any:
        keywords: list[str] = []
        order_spec: list[tuple[Any, bool]] = []
        partition_refs: list[tuple[Any, ...]] = []
        match_refs: list[tuple[Any, ...]] = []
        relation = None
        for argument in arguments:
            if argument[0] == "omitted":
                continue
            if argument[0] == "table":
                keywords.append(str(argument[1]).upper())
            elif argument[0] == "call" and argument[1] == "ORDERBY":
                order_spec = order_arguments_asc(argument[2])
            elif argument[0] == "call" and argument[1] == "PARTITIONBY":
                partition_refs = list(argument[2])
            elif argument[0] == "call" and argument[1] == "MATCHBY":
                match_refs = list(argument[2])
            elif relation is None and (_is_general_table_filter(argument) or (argument[0] == "call" and argument[1] in {"ALL", "ALLEXCEPT", "ALLSELECTED", "ALLNOBLANKROW", "VALUES", "DISTINCT"})):
                relation = argument
            else:
                raise MeasureError(f"{function} has an argument the local engine does not support.")
        if relation is None:
            raise MeasureError(f"{function}'s relation parameter must be a table in non-visual calculation mode.")
        if function in {"INDEX", "OFFSET", "WINDOW"} and relation_may_have_duplicates(relation):
            raise MeasureRuntimeError(f"{function}'s Relation parameter may have duplicate rows. This is not allowed.")
        window = _Window()
        window.context, window.rows = table_argument_value(relation)
        window.typed = [typed_row(window.context, row) for row in window.rows]
        window.keywords = keywords
        headers = list(window.context["headers"])
        header_by_key = {h.casefold(): h for h in headers}

        def column(reference: tuple[Any, ...]) -> str:
            actual = header_by_key.get(str(reference[2]).casefold())
            if actual is None:
                raise MeasureError(f"Column {reference[2]!r} does not exist in the relation of {function}.")
            return actual

        window.partition_columns = [column(reference) for reference in partition_refs]
        keys: list[list[Any]] = []
        for frame in iterate_rows(window.context, window.rows):
            keys.append([evaluate(expression, frame, allow_text=True) for expression, _desc in order_spec])
        window.order_keys = keys
        window.order_desc = [desc for _expression, desc in order_spec]
        tie_columns = [h for h in headers if h not in window.partition_columns]
        window.tie_columns = tie_columns
        total = list(range(len(window.rows)))
        if not order_spec:
            window.order_keys = [[window.typed[i][h] for h in headers] for i in total]
            window.order_desc = [False] * len(headers)
        for position in range(len(tie_columns) - 1, -1, -1):  # then every relation column ascending
            pass
        full_keys = [window.order_keys[i] + [window.typed[i][h] for h in tie_columns] for i in total]
        full_desc = window.order_desc + [False] * len(tie_columns)
        window.sort_keys = [blank_aware_keys([full_keys[i][position] for i in total]) for position in range(len(full_desc))]
        ordered = list(total)
        for position in range(len(full_desc) - 1, -1, -1):
            ordered.sort(key=lambda i, p=position: window.sort_keys[p][i], reverse=full_desc[position])
        window.ordered = ordered
        partitions: dict[tuple[Any, ...], list[int]] = {}
        for i in ordered:
            partitions.setdefault(row_key(window.typed[i][c] for c in window.partition_columns), []).append(i)
        window.partitions = partitions
        window.partition_of = {i: key for key, members in partitions.items() for i in members}
        lineage = window.context.get("lineage")
        if lineage is None and not window.context.get("derived"):
            lineage = {h: (window.context, h) for h in headers}
        groups: dict[str, tuple[dict[str, Any], list[tuple[str, str]]]] = {}
        for header in headers:
            link = (lineage or {}).get(header)
            if link is not None:
                groups.setdefault(link[0]["id"], (link[0], []))[1].append((header, link[1]))
        visible: dict[str, set[tuple[Any, ...]]] = {}
        for table_id, (base_context, pairs) in groups.items():
            # Power BI also reads the row contexts on the stack as filters on the base table (columns that carry lineage).
            constraints: list[dict[str, Any]] = []
            for frame_context, frame_row, _index in row_stack:
                if frame_context.get("boolean_filter"):
                    continue
                if frame_context.get("derived"):
                    frame_lineage = frame_context.get("lineage") or {}
                    constraint = {
                        link[1]: frame_row.get(header) for header, link in frame_lineage.items()
                        if link[0].get("id") == table_id and header in frame_row
                    }
                else:
                    constraint = (
                        {name: typed_cell(base_context, name, frame_row.get(name)) for name in base_context["headers"] if name in frame_row}
                        if frame_context.get("id") == table_id else {}
                    )
                if constraint:
                    constraints.append(constraint)
            if len(constraints) > 1:
                # live Power BI (iteration 88, fresh probes): under two row contexts of the relation's table (SUMX(Facts, SUMX(VALUES(Region), OFFSET(..))))
                # the answer is not the intersection of both; which of them Power BI reads was not established
                raise MeasureError(f"{function} under several row contexts of its relation's table is not supported in the local engine.")
            visible[table_id] = {
                row_key(typed_cell(base_context, column_name, vrow.get(column_name)) for _h, column_name in pairs)
                for vrow in rows_by_table_id[table_id]
                if all(
                    all(typed_cell(base_context, name, vrow.get(name)) == value for name, value in constraint.items())
                    for constraint in constraints
                )
            }
        window.current = [
            i for i in total
            if all(
                row_key(window.typed[i][h] for h, _c in pairs) in visible[table_id]
                for table_id, (_b, pairs) in groups.items()
            )
        ]
        window.order_equal = lambda a, b: row_key(window.order_keys[a]) == row_key(window.order_keys[b])
        return window

    def order_arguments_asc(arguments: tuple[tuple[Any, ...], ...]) -> list[tuple[Any, bool]]:
        spec: list[tuple[Any, bool]] = []
        index = 0
        while index < len(arguments):
            descending, expression = False, arguments[index]
            index += 1
            if index < len(arguments):
                direction = arguments[index]
                if direction[0] == "table" and str(direction[1]).upper() in {"ASC", "DESC"}:
                    descending = str(direction[1]).upper() == "DESC"
                    index += 1
                elif direction[0] in {"number", "boolean"}:
                    if direction[1] not in (0, 1):
                        raise MeasureError("Unexpected value for the ORDER argument. Use 0/FALSE/DESC for descending or 1/TRUE/ASC for ascending.")
                    descending = direction[1] == 0 or direction[1] is False
                    index += 1
            spec.append((expression, descending))
        return spec

    def window_table(function: str, arguments: tuple[tuple[Any, ...], ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        def scalar(node: tuple[Any, ...]) -> Any:
            return evaluate(node, None, allow_text=True)

        if function == "WINDOW":
            from_node = arguments[0]
            position = 1
            from_type = "REL"
            if position < len(arguments) and arguments[position][0] == "table" and str(arguments[position][1]).upper() in {"ABS", "REL"}:
                from_type = str(arguments[position][1]).upper()
                position += 1
            elif position < len(arguments) and arguments[position][0] == "omitted":
                position += 1
            to_node = arguments[position]
            position += 1
            to_type = "REL"
            if position < len(arguments) and arguments[position][0] == "table" and str(arguments[position][1]).upper() in {"ABS", "REL"}:
                to_type = str(arguments[position][1]).upper()
                position += 1
            elif position < len(arguments) and arguments[position][0] == "omitted":
                position += 1
            rest = arguments[position:]
        else:
            lead = arguments[0]
            rest = arguments[1:]
        window = window_setup(tuple(rest), function)
        selected: set[int] = set()
        if function == "INDEX":
            value = scalar(lead)
            if value is None:
                return window.context, []
            if "FIRST" in window.keywords or "LAST" in window.keywords:
                raise MeasureRuntimeError("Blanks parameter is not allowed in this context in INDEX function.")
            index_value = int(dax_typed.to_number(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            for members in window.partitions.values():
                target = index_value - 1 if index_value > 0 else len(members) + index_value if index_value < 0 else -1
                if 0 <= target < len(members):
                    selected.add(members[target])
        else:
            current_by_partition: dict[tuple[Any, ...], list[int]] = {}
            for i in window.current:
                current_by_partition.setdefault(window.partition_of[i], []).append(i)
            if function == "OFFSET":
                delta_value = scalar(lead)
                delta = 0 if delta_value is None else int(dax_typed.to_number(delta_value).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                for key, current_rows in current_by_partition.items():
                    members = window.partitions[key]
                    for i in current_rows:
                        target = members.index(i) + delta
                        if 0 <= target < len(members):
                            selected.add(members[target])
            else:
                from_value = int(dax_typed.to_number(scalar(from_node) or Decimal(0)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                to_value = int(dax_typed.to_number(scalar(to_node) or Decimal(0)).quantize(Decimal(1), rounding=ROUND_HALF_UP))

                def bound(value: int, kind: str, current: int, count: int) -> int:
                    if kind == "REL":
                        return current + value
                    return value - 1 if value > 0 else count + value if value < 0 else 0

                if "ABS" in (from_type, to_type) and "REL" not in (from_type, to_type):
                    for members in window.partitions.values():
                        low = max(bound(from_value, from_type, 0, len(members)), 0)
                        high = min(bound(to_value, to_type, 0, len(members)), len(members) - 1)
                        selected.update(members[low:high + 1] if low <= high else [])
                else:
                    for key, current_rows in current_by_partition.items():
                        members = window.partitions[key]
                        for i in current_rows:
                            where = members.index(i)
                            low = max(bound(from_value, from_type, where, len(members)), 0)
                            high = min(bound(to_value, to_type, where, len(members)), len(members) - 1)
                            selected.update(members[low:high + 1] if low <= high else [])
        return window.context, [window.rows[i] for i in window.ordered if i in selected]

    def window_scalar(function: str, arguments: tuple[tuple[Any, ...], ...]) -> Any:
        rest = arguments
        ties = "SKIP"
        if function == "RANK" and rest and rest[0][0] == "table" and str(rest[0][1]).upper() in {"DENSE", "SKIP"}:
            ties = str(rest[0][1]).upper()
            rest = rest[1:]
        if function == "ROWNUMBER" and any(argument[0] == "omitted" for argument in rest):
            raise MeasureError("An argument of the ROWNUMBER function is required; it cannot be omitted.")
        window = window_setup(tuple(rest), function)
        current = window.current
        if len(current) != 1:
            return None
        row = current[0]
        members = window.partitions[window.partition_of[row]]
        if function == "ROWNUMBER":
            return Decimal(members.index(row) + 1)
        keys_before = {row_key(window.order_keys[m]) for m in members if row_key(window.order_keys[m]) != row_key(window.order_keys[row]) and sorted_before(window, m, row)}
        if ties == "DENSE":
            return Decimal(len(keys_before) + 1)
        return Decimal(1 + sum(1 for m in members if row_key(window.order_keys[m]) != row_key(window.order_keys[row]) and sorted_before(window, m, row)))

    def sorted_before(window: Any, other: int, row: int) -> bool:
        """Whether `other` ranks strictly before `row` on the ORDERBY keys alone."""
        for position, descending in enumerate(window.order_desc[: len(window.order_keys[row])]):
            ka, kb = window.sort_keys[position][other], window.sort_keys[position][row]
            if ka == kb:
                continue
            return (ka > kb) if descending else (ka < kb)
        return False

    def order_distinct_values(
        context: dict[str, Any], column: str, value_rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Distinct values in storage order: numbers and dates ascending, text by first appearance in the table."""
        kind = str(context.get("column_types", {}).get(column, "text")).casefold()
        if kind in _COLUMN_NUMBER_TYPES or kind in {"date", "datetime"}:
            try:
                wide = not dax_iteration_order.grouped(len(context["rows"]), [source_profile(context, column)], True)
            except (MeasureError, ArithmeticError, ValueError, TypeError):  # a cell this cannot place: sort as before
                wide = False
            if wide:
                return value_rows  # a wide range keeps first-appearance order
            def is_blank(value: Any) -> bool:
                # An empty loaded cell in a number or date column is a blank, like the virtual unmatched-key row.
                return value is None or (isinstance(value, str) and not value.strip())

            return sorted(
                value_rows,
                key=lambda row: (
                    not is_blank(row[column]),
                    0 if is_blank(row[column]) else typed_cell(context, column, row[column]),
                ),
            )
        if kind == "boolean":  # BLANK, FALSE, TRUE
            return sorted(value_rows, key=lambda row: (row[column] is not None, typed_cell(context, column, row[column]) if row[column] is not None else False))
        first_seen: dict[Any, int] = {}
        for position, base in enumerate(context["rows"]):
            value = base.get(column)
            first_seen.setdefault(cell_key(ascii_fold(value) if isinstance(value, str) else value), position)
        return sorted(  # a BLANK is the first entry of every dictionary (Power BI, tools/parity/dax_battery_concatenatex_order.json)
            value_rows,
            key=lambda row: -1 if row[column] is None else first_seen.get(cell_key(ascii_fold(row[column]) if isinstance(row[column], str) else row[column]), 0),
        )

    iterator_depth = 0
    variable_nodes: dict[str, Any] = {}  # VAR name -> the expression it was declared with (to walk a table held in a VAR)
    topn_walk_nodes: dict[int, list[tuple[Any, ...]]] = {}  # id of a TOPN node -> expressions its CONCATENATEX consumer reads
    lazy_column_calls: list[Any] = []  # ADDCOLUMNS/SELECTCOLUMNS nodes whose columns COUNTROWS never reads

    def in_row_expression(thunk: Any) -> Any:
        """Run a row-level expression: an error it throws cannot be caught by IFERROR or ISERROR."""
        nonlocal iterator_depth
        iterator_depth += 1
        try:
            return thunk()
        except _DivisionError:
            raise  # Infinity and NaN stay error values
        except (MeasureRuntimeError, DecimalException, OverflowError) as error:
            if getattr(error, "infinity", False):
                raise
            raise _HardError(str(error)) from error
        finally:
            iterator_depth -= 1

    def conjuncts_pass(predicate: tuple[Any, ...], frame: tuple[dict[str, Any], dict[str, Any], int]) -> bool:
        """A FILTER row test. A top-level && chain (or AND) is split: plan-time constants are decided once up front, a conjunct
        that does not read the row is evaluated once up front too (its error is raised even when no row would reach it, its
        value is applied in its place), and the rest run left to right on the rows still alive, so a guard really guards."""
        parts = logical_conjuncts(predicate)

        def holds(part: tuple[Any, ...]) -> bool:
            return dax_typed.to_boolean(in_row_expression(
                lambda: evaluate(part, frame, allow_text=True, allow_boolean=True)))

        if len(parts) == 1:
            return holds(parts[0])
        key = (id(predicate), current_context, tuple(id(item[1]) for item in row_stack[:-1]))
        if key not in conjunct_constants:
            decided: bool | None = True
            failure: MeasureError | None = None
            ordered: list[tuple[tuple[Any, ...], bool | None]] = []  # (conjunct, its value when it does not read the row)
            for part in parts:
                if reads_row(part):
                    ordered.append((part, None))
                    continue
                try:
                    value = holds(part)
                except MeasureError as error:
                    failure = failure or error
                    value = None
                if plan_constant(part):
                    if value is False:
                        decided = False
                    ordered.append((part, True if value is not False else False))
                else:
                    ordered.append((part, value))
            if decided is False:
                failure = None  # a constant FALSE settles the filter; a closed error elsewhere is swallowed
            conjunct_constants[key] = (decided, failure, ordered)
        decided, failure, ordered = conjunct_constants[key]
        if failure is not None:
            raise failure
        if not decided:
            return False
        for part, closed_value in ordered:
            if not (holds(part) if closed_value is None else closed_value):
                return False
        return True

    def table_function_value(argument: tuple[Any, ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """A table function's rows; VALUES/DISTINCT/ALL of columns and SUMMARIZE come out in Power BI's dictionary order."""
        context, rows = table_function_rows(argument)
        walk = dax_iteration_order.plan(argument)
        if walk is not None and walk.dedup and len(rows) > 1:
            lineage = base_lineage(context)
            rows = dictionary_ordered_rows(argument, context, rows, [("reference", "", h) for h in context["headers"] if h in lineage])
        return context, rows

    def cell_to_date(context: dict[str, Any], header: str, value: Any) -> date | None:
        """A cell of a date column (loaded text or a typed DateTime) as a calendar date; blank is None."""
        if value is None:
            return None
        if isinstance(value, dax_dates.DaxDateTime):
            return dax_dates.to_datetime(value).date()
        if isinstance(value, (Decimal, bool)):
            raise MeasureError("Time-intelligence functions need a column or table of dates.")
        return _parse_measure_date(value, header, 0)

    def constant_year_end(node: tuple[Any, ...] | None) -> tuple[int, int]:
        """The optional year-end argument: a constant only (Power BI refuses an expression), read like an OLE date."""
        if node is None or node[0] == "blank":
            return dax_time_sets.DEFAULT_YEAR_END
        if node[0] in {"string", "number", "boolean"}:
            value = node[1]
        elif node[0] == "unary" and node[1] in {"+", "-"} and node[2][0] == "number":
            value = node[2][1] if node[1] == "+" else -node[2][1]
        else:
            raise MeasureError("Only constant date value is allowed as a year end date argument.")
        try:
            return dax_time_sets.parse_year_end_value(value)
        except dax_time_sets.TimeSetError as error:
            raise MeasureError(str(error)) from error

    def date_column_source(source: tuple[Any, ...], function: str) -> tuple[dict[str, Any], str, list[date], list[date], dict[date, Any]]:
        """(base table, column, V, U, raw cell of each date) of the dates a time function was given.

        V: the dates visible now (the column's visible rows, or the dates of the table expression); U: every date of the column."""
        if source[0] == "reference":
            context, column = resolve_table(source[1], source[2])
            visible_rows: list[dict[str, Any]] | Iterable[dict[str, Any]] = rows_by_table_id[context["id"]]
            row_filters = all_row_context_filters(None) if row_stack else {}
            if row_filters:
                # live Power BI (iteration 84, critic): inside an iterator the row of the iterated table filters a bare date column, like
                # the transition of a CALCULATE around the date set does
                visible_rows = with_column_filters(row_filters, lambda: list(rows_by_table_id[context["id"]]), True)
            base, base_column, viewed = context, column, True
        else:
            if source[0] == "call" and source[1] in {"DATE", "TIME", "TODAY", "NOW", "MAX", "MIN", "EDATE", "EOMONTH"}:
                raise MeasureError(f"{function} needs a column of dates, not a single date value.")
            table_context, visible_rows = table_argument_value(source)
            if len(table_context["headers"]) != 1:
                raise MeasureError(f"{function} needs a table with one column of dates.")
            header = table_context["headers"][0]
            link = (table_context.get("lineage") or {}).get(header)
            if link is None and not table_context.get("derived"):
                link = (table_context, header)
            if link is None:
                raise MeasureError(f"{function} needs dates that come from a column of the model.")
            base, base_column, viewed = contexts_by_id.get(link[0]["id"], link[0]), link[1], False
            visible_rows = [{base_column: row.get(header)} for row in visible_rows]
            table_context = {**table_context, "headers": [base_column]}
        if str(base.get("column_types", {}).get(base_column, "")).casefold() not in {"date", "datetime"}:
            raise MeasureError(f"{function} needs a Date or DateTime column.")
        raw_by_date: dict[date, Any] = {}
        universe: list[date] = []
        for row_index, row in enumerate(base["rows"], 1):
            day = cell_to_date(base, base_column, row.get(base_column))
            if day is not None and day not in raw_by_date:
                raw_by_date[day] = row.get(base_column)
                universe.append(day)
        visible: list[date] = []
        seen_days: set[date] = set()
        for row in visible_rows:
            day = cell_to_date(base, base_column, row.get(base_column))
            if day is not None and day not in seen_days:
                seen_days.add(day)
                visible.append(day)
        for day in visible:
            if day not in raw_by_date:  # a date of a derived table that the column does not hold
                raise MeasureError(f"{function} needs dates that come from the column of the model.")
        return base, base_column, visible, universe, raw_by_date

    def date_bound(node: tuple[Any, ...], function: str) -> date | None:
        return _scalar_day(in_row_expression(lambda: evaluate(node, None, allow_text=True)), function)

    def date_set_table(node: tuple[Any, ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """FIRSTDATE .. DATESBETWEEN as a one-column table with the lineage of the date column (live Power BI, iteration 84)."""
        function, arguments = node[1], node[2]
        year_end = dax_time_sets.DEFAULT_YEAR_END
        bounds: tuple[date | None, date | None] = (None, None)
        if function == "DATESBETWEEN":
            bounds = (date_bound(arguments[1], function), date_bound(arguments[2], function))
        elif function in dax_time_sets.YEAR_END_FUNCTIONS:
            year_end = constant_year_end(arguments[1] if len(arguments) == 2 else None)
        base, column, visible, universe, raw_by_date = date_column_source(arguments[0], function)
        if year_end == (2, 28) and function in {"NEXTYEAR", "PREVIOUSYEAR"} and visible:
            anchor = max(visible) if function == "NEXTYEAR" else min(visible)
            if (anchor.month, anchor.day) >= (2, 27) and (anchor.month, anchor.day) <= (3, 2):
                # open item of the live comparison: around a leap day Power BI starts the fiscal year on Feb 29
                raise MeasureError(f"{function} with a February 28 year end is not supported near a leap day in the local engine.")
        chosen = dax_time_sets.date_set(function, visible, universe, year_end, bounds)
        single = dict(base)
        single["headers"] = [column]
        single["lineage"] = {column: (base, column)}
        single["single_column_set"] = True
        return single, [{column: raw_by_date[day]} for day in chosen]

    def nonblank_candidates(function: str, source: tuple[Any, ...]) -> tuple[dict[str, Any], str, bool, list[tuple[Any, Any]]]:
        """(base table, column, typed cells?, [(raw cell, value)]) the distinct non-blank values of the column visible now, ascending
        (FIRST) or descending (LAST)."""
        derived_source = False
        if source[0] == "reference":
            base, column = resolve_table(source[1], source[2])
            row_filters = all_row_context_filters(None) if row_stack else {}  # the row of an enclosing iterator filters the column (see date_column_source)
            rows = with_column_filters(row_filters, lambda: list(rows_by_table_id[base["id"]]), True) if row_filters else rows_by_table_id[base["id"]]
        else:
            table_context, table_rows = table_argument_value(source)
            if len(table_context["headers"]) != 1:
                raise MeasureError(f"{function} needs a table with one column.")
            header = table_context["headers"][0]
            link = (table_context.get("lineage") or {}).get(header)
            if link is None and not table_context.get("derived"):
                link = (table_context, header)
            if link is None:
                raise MeasureError(f"{function} needs values that come from a column of the model.")
            base, column = contexts_by_id.get(link[0]["id"], link[0]), link[1]
            derived_source = bool(table_context.get("derived"))
            rows = [{column: row.get(header)} for row in table_rows]
        distinct: dict[Any, tuple[Any, Any]] = {}
        for source_row in rows:
            raw = source_row.get(column)
            if raw is None:
                continue
            typed = raw if derived_source else typed_cell(base, column, raw)
            distinct.setdefault(cell_key(ascii_fold(typed) if isinstance(typed, str) else typed), (raw, typed))
        ordered = sorted(distinct.values(), key=lambda pair: column_order_key(pair[1]), reverse=function.startswith("LAST"))
        return base, column, derived_source, ordered

    def nonblank_pick(
        function: str, arguments: tuple[tuple[Any, ...], ...],
        candidates: tuple[dict[str, Any], str, bool, list[tuple[Any, Any]]] | None = None,
    ) -> tuple[dict[str, Any], str, Any, Any]:
        """FIRSTNONBLANK / LASTNONBLANK(+VALUE): (base table, column, raw cell, value of the expression) of the first candidate whose
        expression is not blank; the cell is None when there is none.

        The plain variants evaluate the expression without a row-to-filter transition (only a CALCULATE inside it transitions); the
        ...VALUE variants evaluate it with the transition (live Power BI, iteration 84)."""
        base, column, derived_source, ordered = candidates or nonblank_candidates(function, arguments[0])
        single = dict(base)
        single["headers"] = [column]
        single["lineage"] = {column: (base, column)}
        with_value = function.endswith("VALUE")
        if with_value and any(
            isinstance(relationship, dict) and relationship.get("is_active") and relationship.get("cardinality") == "one_to_one"
            and base["id"] in {str(relationship.get("from_table_id", "")), str(relationship.get("to_table_id", ""))}
            and ({str(relationship.get("from_table_id", "")), str(relationship.get("to_table_id", ""))} - {base["id"]}) & set(evaluation_filter_ids)
            for relationship in relationship_definitions
        ):
            # live Power BI (iteration 84, critic): LASTNONBLANKVALUE over a column of a one-to-one table whose partner is filtered tries the
            # partner's unmatched rows in a way not modelled here (-1, ours 0)
            raise MeasureError("FIRSTNONBLANKVALUE / LASTNONBLANKVALUE over a table filtered through a one-to-one relationship is not supported in the local engine.")
        for raw, _typed in ordered:
            row = {column: _typed if derived_source else raw}
            if with_value:
                result = evaluate_with_context_transition(arguments[1], single, row)
            else:
                result = None
                for frame in iterate_rows(single, [row]):
                    result = in_row_expression(lambda frame=frame: evaluate(arguments[1], frame, allow_text=True))
            if result is not None:
                return base, column, raw, result
        return base, column, None, None

    def nonblank_table(
        node: tuple[Any, ...], candidates: tuple[dict[str, Any], str, bool, list[tuple[Any, Any]]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        base, column, raw, _value = nonblank_pick(node[1], node[2], candidates)
        single = dict(base)
        single["headers"] = [column]
        single["lineage"] = {column: (base, column)}
        single["single_column_set"] = True
        return single, ([] if raw is None else [{column: raw}])

    _SCALAR_PASS_CALLS = frozenset({"IF", "SWITCH", "IFERROR", "COALESCE", "ABS", "ROUND", "INT", "AND", "OR", "NOT", "ISBLANK", "DIVIDE"})
    _NESTED_BODY_ITERATORS = frozenset({"SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CONCATENATEX", "FILTER", "XNPV"})

    def static_table_columns(node: Any) -> set[tuple[str, str]] | None:
        """The (table id, column) pairs the rows of a table expression hold, or None when that is not known without evaluating it."""
        try:
            if node[0] == "table":
                held = resolve_table_context(str(node[1]))
                return {(held["id"], str(header).casefold()) for header in held["headers"]}
            if node[0] == "table_call" and node[1] in {"VALUES", "DISTINCT"} and len(node) == 3:
                if node[2][0] == "reference":
                    held, column = resolve_table(node[2][1], node[2][2])
                    return {(held["id"], column.casefold())}
                return static_table_columns(node[2])
            if node[0] == "call" and node[2]:
                name, arguments = node[1], node[2]
                if name in {"VALUES", "DISTINCT", "ALL", "ALLNOBLANKROW", "ALLSELECTED"}:
                    if all(argument[0] == "reference" for argument in arguments):
                        found = set()
                        for argument in arguments:
                            held, column = resolve_table(argument[1], argument[2])
                            found.add((held["id"], column.casefold()))
                        return found
                    if len(arguments) == 1:
                        return static_table_columns(arguments[0])
                if name == "ROW":
                    return set()  # named columns only: no column of a model table
                if name in {"FILTER", "CALCULATETABLE", "ADDCOLUMNS"}:
                    return static_table_columns(arguments[0])
                if name == "TOPN" and len(arguments) > 1:
                    return static_table_columns(arguments[1])
        except MeasureError:
            return None
        return None

    def earlier_unreadable_deep(node: Any, frames: list[Any]) -> bool:
        """Like `_earlier_unreadable`, but follows the iterators nested in the body: each opens a row context holding the columns of its table (None
        when those are not known statically, which proves nothing).  An EARLIER / EARLIEST of a bare [name] (an alias, never a table column) is
        an error in Power BI wherever it stands."""
        if not isinstance(node, tuple) or not node:
            return False
        if node[0] == "call" and node[1] in {"EARLIER", "EARLIEST"} and node[2] and node[2][0][0] == "reference":
            reference = node[2][0]
            if not reference[1]:
                return True
            depth = 1
            if node[1] == "EARLIER" and len(node[2]) > 1 and node[2][1][0] == "number":
                depth = int(node[2][1][1])
            remaining = frames[:1] if node[1] == "EARLIEST" else frames[:-depth] if depth >= 1 else []
            if not remaining:
                return False
            try:
                held, column = resolve_table(reference[1], reference[2])
            except MeasureError:
                return False
            for holder in remaining:
                if holder is None:
                    continue
                if isinstance(holder, tuple) and holder[0] == "frame":
                    if column_in_row_context(holder[1], reference[1], reference[2]):
                        return False
                elif isinstance(holder, tuple) and holder[0] == "columns":
                    if (held["id"], column.casefold()) in holder[1]:
                        return False
                else:
                    return False  # a row context whose columns are not known
            return True
        if node[0] == "call" and node[1] in _NESTED_BODY_ITERATORS and node[2]:
            columns = static_table_columns(node[2][0])
            holder: Any = ("columns", columns) if columns is not None else "unknown"
            return any(earlier_unreadable_deep(argument, [*frames, holder]) for argument in node[2][1:])
        if node[0] in {"table", "table_call"}:
            return False
        return any(earlier_unreadable_deep(child, frames) for child in node if isinstance(child, tuple))

    def unreachable_foreign_reference(
        node: Any, readable: Callable[[str, str], bool], extra: frozenset[tuple[str, str]], is_alias: Callable[[str], bool],
    ) -> None:
        """Iteration 88 (live Power BI, fresh nested-iterator probes): the body of an iteration that has no rows is still validated, including the
        bodies of the iterators nested in it: a column of a table the nested iteration does not hold and no enclosing row context holds is an error
        there too (the local engine would answer BLANK because the nested body never runs).  Only scalar positions and nested iterators whose
        table's columns are known statically are followed."""
        if not isinstance(node, tuple) or not node:
            return
        if node[0] == "reference":
            if not node[1]:
                if not extra and is_alias(node[2]):
                    # live Power BI (fresh probes): [alias] of a SELECTCOLUMNS / ADDCOLUMNS row context read in the body of an iteration with no rows
                    # is an error; the answer for a non-empty one is not modelled here
                    raise MeasureError("An alias column read in the body of an empty iteration is not supported in the local engine.")
                return
            try:
                held, column = resolve_table(node[1], node[2])
            except MeasureError:
                return
            if (held["id"], column.casefold()) in extra or readable(node[1], node[2]):
                return
            raise MeasureError("Iterator expressions can reference columns from their iterated table only.")
        if node[0] == "call":
            name, arguments = node[1], node[2]
            if name in _NESTED_BODY_ITERATORS and arguments:
                columns = static_table_columns(arguments[0])
                if columns is not None:
                    for argument in arguments[1:]:
                        unreachable_foreign_reference(argument, readable, extra | frozenset(columns), is_alias)
                return
            if name in _SCALAR_PASS_CALLS:
                for argument in arguments:
                    unreachable_foreign_reference(argument, readable, extra, is_alias)
            return
        if node[0] in {"table", "number", "string", "boolean", "blank", "table_call"}:
            return
        for child in node[1:]:
            if isinstance(child, tuple):
                unreachable_foreign_reference(child, readable, extra, is_alias)

    def refuse_foreign_columns_of_empty_iteration(context: dict[str, Any], *expressions: tuple[Any, ...]) -> None:
        """Live Power BI (iteration 84, testing agent; 34 of 12,534 fresh probes): an iterator body that reads a column of a table other than
        the iterated one is evaluated once without a row even when the iteration is empty, and fails with "a single value for column ...
        cannot be determined" whenever the filter context holds several values of it (SUMX(FILTER(Cal, FALSE()), Fact[Amt]), the body of a
        TOPN / FILTER / CONCATENATEX over an empty set, an untaken SWITCH branch).  The local engine only runs a body per row, so an empty
        iteration would answer BLANK; the same refusal as for a non-empty iteration is raised instead."""
        lineage = context.get("lineage") or {}
        headers = {str(header).casefold() for header in context.get("headers", [])}
        for expression in expressions:
            if (
                _earlier_unreadable(expression, [*row_stack, None], column_in_row_context)
                or _earlier_too_deep(expression, len(row_stack) + 1)
                or earlier_unreadable_deep(expression, [*(("frame", frame) for frame in row_stack), None])
            ):
                # live Power BI (iteration 88, fresh probes): EARLIER / EARLIEST is validated against the row contexts around the iteration also when it
                # has no rows (an error when too few); the local engine would answer BLANK without running the body
                raise MeasureRuntimeError("EARLIER/EARLIEST refers to an earlier row context which doesn't exist.")
            for reference in _direct_column_references(expression):
                if not reference[1]:
                    continue  # a measure or a column of the iterated table
                try:
                    table, column = resolve_table(reference[1], reference[2])
                except MeasureError:
                    continue  # the evaluation of a non-empty iteration reports it
                if table["id"] == context.get("id") and column.casefold() in headers:
                    continue
                if any(base["id"] == table["id"] and str(base_column).casefold() == column.casefold() for base, base_column in lineage.values()):
                    continue
                if any(column_in_row_context(frame, reference[1], reference[2]) for frame in row_stack if not frame[0].get("boolean_filter")):
                    continue  # an enclosing row context holds the column (iteration 88): its one value is read
                raise MeasureError("Iterator expressions can reference columns from their iterated table only.")

            def alias_of_enclosing_frame(name: str) -> bool:
                if name.casefold() in headers:
                    return False
                return any(
                    frame[0].get("derived") and any(str(header).casefold() == name.casefold() for header in frame[0].get("headers", []))
                    for frame in row_stack if not frame[0].get("boolean_filter")
                )

            def readable(table_name: str, column_name: str) -> bool:
                held, column = resolve_table(table_name, column_name)
                if held["id"] == context.get("id") and column.casefold() in headers:
                    return True
                if any(base["id"] == held["id"] and str(base_column).casefold() == column.casefold() for base, base_column in lineage.values()):
                    return True
                return any(column_in_row_context(frame, table_name, column_name) for frame in row_stack if not frame[0].get("boolean_filter"))

            unreachable_foreign_reference(expression, readable, frozenset(), alias_of_enclosing_frame)

    def refuse_foreign_columns_of_empty_set(context: dict[str, Any], expression: tuple[Any, ...]) -> None:
        """Power BI rejects an iterator body that reads a column other than the one a date set holds, also when the set is empty
        (live: MAXX(NEXTDAY(Fact[Dt]), Fact[Ship]) and MAXX(set, Cal[Date]) are errors)."""
        refuse_foreign_columns_of_empty_iteration(context, expression)
        if not context.get("single_column_set"):
            return
        lineage = next(iter(context.get("lineage", {}).values()), None)
        for reference in _direct_column_references(expression):
            if not reference[1]:
                continue
            table, column = resolve_table(reference[1], reference[2])
            if lineage is None or table["id"] != lineage[0]["id"] or column.casefold() != lineage[1].casefold():
                raise MeasureError("The iterated date set has one column; the expression reads another column.")

    def single_value_of(table: tuple[dict[str, Any], list[dict[str, Any]]]) -> Any:
        """A table in a place that wants one value: one row and one column is that value, no rows is BLANK, more is an error."""
        context, rows = table
        if len(context["headers"]) != 1:
            raise MeasureError("A table with several columns was supplied where a single value was expected.")
        if len(rows) > 1:
            raise MeasureRuntimeError("A table of multiple values was supplied where a single value was expected.")
        if not rows:
            return None
        header = context["headers"][0]
        value = rows[0].get(header)
        return value if context.get("derived") else typed_cell(context, header, value)

    def table_argument_value(
        argument: tuple[Any, ...],
        include_unknown: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if argument[0] == "table":
            context = resolve_table_context(str(argument[1]))
            table_rows = rows_by_table_id[context["id"]]
            current_context = evaluation_contexts_by_id.get(
                context["id"], context
            )
            if (
                include_unknown  # live Power BI: only VALUES/ALL-like readers see the unknown member, a base-table reference never does
                and context["id"] in unknown_member_ids
                and not unknown_member_hidden(context["id"])
                and unknown_member_passes_remaining_filters(
                    current_context,
                    evaluation_contexts_by_id,
                    evaluation_filter_ids,
                )
            ):
                table_rows = [
                    *table_rows,
                    {header: None for header in current_context["headers"]},
                ]
            return context, table_rows
        if argument[0] == "call" and argument[1] in dax_time_sets.SET_FUNCTIONS:
            return date_set_table(argument)
        if argument[0] == "call" and argument[1] == "EVALUATEANDLOG":
            return table_argument_value(argument[2][0], include_unknown=include_unknown)
        if argument[0] == "call" and argument[1] in {"FIRSTNONBLANK", "LASTNONBLANK"}:
            return nonblank_table(argument)
        if argument[0] == "tablevalue":  # a table already computed (see evaluate_with_general_filters)
            return argument[1]
        if argument[0] == "call" and argument[1] in _TABLE_FUNCTION_ARITY:
            return table_function_value(argument)
        if argument[0] == "call" and argument[1] in _TIME_FILTER_FUNCTIONS:
            date_table, date_column, days = time_filter_dates(argument)
            days = days & {  # a date set holds only days the column has
                parsed for index, row in enumerate(date_table["rows"], 1)
                if (parsed := _parse_measure_date(row.get(date_column), date_column, index)) is not None
            }
            return derived_table(
                [date_column], [{date_column: dax_dates.from_datetime(day)} for day in sorted(days)],
                {date_column: (date_table, date_column)}, {date_column: "date"},
            )
        if argument[0] == "var":
            held = variables[argument[1]]()
            if not isinstance(held, _TableValue):
                raise MeasureError("This variable does not hold a table.")
            if variable_nodes.get(argument[1], (None,))[0] == "table":
                if not direct_counting_table_vars or direct_counting_table_vars[-1] != argument[1]:
                    raise MeasureError("A bare table variable is supported only as the direct argument to COUNTROWS.")
            return held[0], held[1]
        if argument[0] == "call" and argument[1] == "CURRENTGROUP":
            if not group_stack:
                raise MeasureError("CURRENTGROUP can only be used inside the aggregations of GROUPBY.")
            return {**group_stack[-1][0], "no_shadow": True}, group_stack[-1][1]  # iterating CURRENTGROUP() filters nothing
        if argument[0] == "tableconstructor" and not argument[1]:
            return derived_table(["Value"], [])
        if argument[0] == "tableconstructor":
            items = argument[1]
            width = len(items[0][1]) if items and items[0][0] in {"tuple", "tableconstructor"} else 1
            records = [
                [evaluate(member, None, allow_text=True) for member in (item[1] if item[0] in {"tuple", "tableconstructor"} else (item,))]
                for item in items
            ]
            for column in range(width):  # mixed types become text, Boolean with numbers become numbers
                values = [record[column] for record in records]
                if any(isinstance(value, str) for value in values):
                    for record in records:
                        if record[column] is not None and not isinstance(record[column], str):
                            record[column] = dax_typed.to_text(record[column])
                elif any(isinstance(value, bool) for value in values) and any(isinstance(value, Decimal) for value in values):
                    for record in records:
                        if isinstance(record[column], bool):
                            record[column] = Decimal(int(record[column]))
            names = ["Value"] if width == 1 and (not items or items[0][0] != "tuple") else [f"Value{column + 1}" for column in range(width)]
            return derived_table(names, [dict(zip(names, record)) for record in records])
        if argument[0] == "call" and argument[1] == "GENERATESERIES":
            start = dax_typed.to_number(in_row_expression(lambda: evaluate(argument[2][0])))
            stop = dax_typed.to_number(in_row_expression(lambda: evaluate(argument[2][1])))
            step = dax_typed.to_number(in_row_expression(lambda: evaluate(argument[2][2]))) if len(argument[2]) > 2 else Decimal(1)
            if step <= 0:
                raise MeasureRuntimeError("GenerateSeries function cannot have an IncrementValue less than or equal to zero.")
            series: list[dict[str, Any]] = []
            current = start
            dated = dax_dates.is_date(start) or dax_dates.is_date(stop)  # live Power BI: a series between two dates holds dates
            while current <= stop and len(series) < 1_000_000:
                series.append({"Value": dax_dates.DaxDateTime(current) if dated else current})
                current += step
            return derived_table(["Value"], series)
        if argument[0] == "call" and argument[1] == "ROW":
            pairs = argument[2]
            names = [str(dax_typed.to_text(evaluate(pairs[i]))) for i in range(0, len(pairs), 2)]
            # ROW inside GENERATE / ADDCOLUMNS sees the row of the enclosing iteration (a CALCULATE in it transitions that row)
            enclosing = row_stack[-1] if row_stack else None
            row = in_row_expression(lambda: {name: evaluate(pairs[i + 1], enclosing, allow_text=True) for name, i in zip(names, range(0, len(pairs), 2))})
            return derived_table(names, [row])
        if argument[0] == "table_call":
            source = argument[2]
            if source[0] not in {"table", "reference"}:
                if argument[1] != "DISTINCT":
                    raise MeasureError("VALUES needs a column or a table name.")
                inner_context, inner_rows = table_argument_value(source)
                distinct_rows: list[dict[str, Any]] = []
                seen_inner: set[tuple[Any, ...]] = set()
                for inner_row in inner_rows:
                    key = row_key(typed_row(inner_context, inner_row).values())
                    if key not in seen_inner:
                        seen_inner.add(key)
                        distinct_rows.append(inner_row)
                return inner_context, distinct_rows
            if source[0] == "table":
                context, source_rows = table_argument_value(source, include_unknown=argument[1] == "VALUES")
                seen_rows: set[tuple[Any, ...]] = set()
                unique_rows = []
                for source_row in source_rows:
                    key = tuple(cell_key(ascii_fold(v) if isinstance(v, str) else v) for v in source_row.values())
                    if argument[1] == "DISTINCT" and key in seen_rows:
                        continue
                    seen_rows.add(key)
                    unique_rows.append(source_row)
                return context, unique_rows
            context, actual = resolve_table(source[1], source[2])
            held = evaluation_contexts_by_id.get(context["id"], {})
            if argument[1] == "VALUES" and held.get("filter_column_rows") and not eff_transition.get(context["id"]) and any(  # a table with a many-side child
                isinstance(item, dict) and item.get("is_active") and (
                    (item.get("cardinality") == "many_to_one" and str(item.get("to_table_id")) == context["id"])
                    or (item.get("cardinality") == "one_to_many" and str(item.get("from_table_id")) == context["id"])
                )
                for item in relationship_definitions
            ) and all(
                getattr(rows, "peer", False) and rows.blank for rows in held["filter_column_rows"].values()
            ):
                # live Power BI (iteration 84, testing agent): CALCULATE(COUNTROWS(VALUES(U[K])), ALLNOBLANKROW(W)) is 3 where the blank member
                # reached through W's orphan row would make 4: whether a one-to-one partner lists it is not modelled
                raise MeasureError("VALUES of a table narrowed through the orphan row of its one-to-one partner is not supported in the local engine.")
            seen: set[tuple[Any, ...]] = set()
            value_rows: list[dict[str, Any]] = []
            for row_index, source_row in enumerate(rows_by_table_id[context["id"]], 1):
                value = source_row.get(actual)
                _reject_power_query_error(value, actual, row_index)
                key = cell_key(ascii_fold(value) if isinstance(value, str) else value)
                if key not in seen:
                    seen.add(key)
                    value_rows.append({actual: value})
            if (
                argument[1] == "VALUES"  # live Power BI: VALUES lists the virtual blank member while it is visible, DISTINCT never does
                and context["id"] in unknown_member_ids
                and not unknown_member_hidden(context["id"])
                and cell_key(None) not in seen
                and unknown_member_passes_remaining_filters(
                    evaluation_contexts_by_id.get(context["id"], context), evaluation_contexts_by_id, evaluation_filter_ids,
                )
            ):
                unknown_row = [{actual: None}]  # unsorted, it comes after the stored values
            else:
                unknown_row = []
            single_column = dict(context)
            single_column["headers"] = [actual]
            single_column["lineage"] = {actual: (context, actual)}
            return single_column, order_distinct_values(context, actual, value_rows) + unknown_row
        if argument[0] == "call" and argument[1] == "ALLEXCEPT":
            kept_context = resolve_table_context(str(argument[2][0][1]))
            if any(  # live Power BI (iteration 84, testing agent): the blank member of a one-to-one partner is part of this table; not modelled
                isinstance(item, dict) and item.get("is_active") and item.get("cardinality") == "one_to_one"
                and kept_context["id"] in {str(item.get("from_table_id")), str(item.get("to_table_id"))}
                for item in relationship_definitions
            ):
                raise MeasureError("ALLEXCEPT over a table of a one-to-one relationship is not supported in the local engine.")
            names_checked = [resolve_table(ref[1], ref[2])[1].casefold() for ref in argument[2][1:]]
            if len(set(names_checked)) != len(names_checked):
                raise MeasureError("ALLEXCEPT was given the same column more than once.")
            # Power BI: the distinct tuples of the columns that are NOT kept, over the whole table with every filter ignored
            remaining = [header for header in kept_context["headers"] if header.casefold() not in names_checked]
            if not remaining:
                raise MeasureError("ALLEXCEPT keeps every column of the table, so it has no columns left.")
            seen_tuples: set[tuple[Any, ...]] = set()
            distinct_rows: list[dict[str, Any]] = []
            for raw in kept_context["rows"]:
                values = {header: typed_cell(kept_context, header, raw.get(header)) for header in remaining}
                key = row_key(values[header] for header in remaining)
                if key not in seen_tuples:
                    seen_tuples.add(key)
                    distinct_rows.append(values)
            return derived_table(
                remaining, distinct_rows, {header: (kept_context, header) for header in remaining},
                {header: kept_context.get("column_types", {}).get(header, "text") for header in remaining},
            )
        if argument[0] == "call" and argument[1] in {
            "ALL", "ALLNOBLANKROW", "ALLSELECTED"
        }:
            return all_table_value(argument)
        if argument[0] == "call" and argument[1] == "FILTER":
            base, predicate = argument[2]
            context, base_rows = table_argument_value(base)
            comparisons: dict[int, tuple[str, str, Any, str]] = {}
            try:
                if context.get("derived") or context.get("lineage") is not None:
                    raise MeasureError("derived table")
                _calculate_table_filter_predicate(predicate, str(context["name"]))
                compile_table_filter_predicate(predicate, context, comparisons)
            except MeasureError:
                # any row predicate: evaluate it for each row, with the row on the EARLIER stack
                if not base_rows:
                    refuse_foreign_columns_of_empty_iteration(context, predicate)
                return context, [frame[1] for frame in iterate_rows(context, base_rows, "install") if conjuncts_pass(predicate, frame)]
            return context, [
                row for position, row in enumerate(base_rows, 1)
                if table_filter_predicate_matches(predicate, row, position, comparisons)
            ]
        raise MeasureError("This table expression is not supported in the local DAX engine.")

    def numeric_values(column: str, table: str) -> list[Decimal]:
        context, actual = resolve_table(table, column)
        values = []
        filtered_rows = rows_by_table_id[context["id"]]
        for row_index, row in enumerate(filtered_rows, 1):
            raw_value = row.get(actual)
            _reject_power_query_error(raw_value, actual, row_index)
            value = "" if raw_value is None else cell_to_text(raw_value).strip()
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

    def as_number(value: Decimal | bool | str | None) -> Decimal:
        return dax_typed.to_number(value)

    def as_boolean(value: Decimal | bool | str | None) -> bool:
        return dax_typed.to_boolean(value)

    def iterator_reference_type(
        reference: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> str:
        if row_context is None:
            return "unknown"
        row_context = enclosing_row_context_for(row_context, reference[1], reference[2], False)
        iterated_table = row_context[0]
        reference_table = (
            resolve_table_context(reference[1])
            if reference[1]
            else iterated_table
        )
        if reference_table["id"] != iterated_table["id"]:
            mapped = next((
                header for header, (base, column) in (iterated_table.get("lineage") or {}).items()
                if base["id"] == reference_table["id"] and column.casefold() == str(reference[2]).casefold()
            ), None)
            if mapped is None:
                raise MeasureError(
                    "Iterator expressions can reference columns from their iterated table only."
                )
            reference, reference_table = (reference[0], "", mapped), iterated_table
        headers_by_key = {
            str(header).casefold(): str(header)
            for header in reference_table["headers"]
        }
        actual_column = headers_by_key.get(str(reference[2]).casefold())
        if actual_column is None:
            raise MeasureError(
                f"Column {reference[2]!r} does not exist in table {reference_table['name']!r}."
            )
        actual_type = reference_table.get("column_types", {}).get(actual_column)
        return "unknown" if actual_type is None else str(actual_type).casefold()

    def join_kind(kinds: list[str]) -> str:
        """The kind of a result that can be any of these branches: Boolean only when every branch is Boolean or BLANK()."""
        if "bool" in kinds and all(kind in {"bool", "blank"} for kind in kinds):
            return "bool"
        return "other"  # only a literal BLANK() joins; an IF/SWITCH whose arms are all blank has no useful type

    def branch_kind(node: tuple[Any, ...], row_context: Any) -> str:
        """Static kind of a result expression: "bool" (Boolean by construction or a Boolean column), "blank" (a literal
        BLANK()) or "other". IF, IFERROR, COALESCE and SWITCH are typed from their own branches."""
        if node == ("blank",) or (node[0] == "unary" and node[-1] == ("blank",)):
            return "blank"
        if node[0] in {"comparison", "logical", "in"}:
            return "bool"
        if node[0] == "unary" and node[1] == "+" and branch_kind(node[2], row_context) == "bool":
            return "bool"  # unary plus leaves a True/False value a Boolean
        if node[0] == "var":
            return variable_kinds.get(node[1], "other")  # a VAR holding BLANK() acts as the literal BLANK()
        if node[0] == "let":
            saved_kinds = dict(variable_kinds)
            try:
                for name, bound in node[1]:
                    variable_kinds[name] = branch_kind(bound, row_context)
                kind = branch_kind(node[2], row_context)
            finally:
                variable_kinds.clear()
                variable_kinds.update(saved_kinds)
            return "other" if kind == "blank" else kind  # a VAR ... RETURN block that is blank has no useful type
        if node[0] == "call":
            function, arguments = node[1], node[2]
            if function in _BOOLEAN_RESULT_CALLS:
                return "bool"
            if function == "IF" and len(arguments) in {2, 3}:
                return join_kind([branch_kind(branch, row_context) for branch in arguments[1:]])
            if function == "IFERROR" and len(arguments) == 2:
                return join_kind([branch_kind(branch, row_context) for branch in arguments])
            if function == "COALESCE" and arguments:
                return join_kind([branch_kind(branch, row_context) for branch in arguments])
            if function == "SWITCH" and len(arguments) >= 3:
                results = list(arguments[1:])
                fallback = results.pop() if len(results) % 2 else None
                rest = None if fallback is None else branch_kind(fallback, row_context)
                for result_branch in reversed(results[1::2]):  # right-nested IFs
                    rest = join_kind([branch_kind(result_branch, row_context)] + ([] if rest is None else [rest]))
                return rest or "other"
        try:
            return "bool" if iterator_expression_category(node, row_context) == "boolean" else "other"
        except MeasureError:
            return "other"

    def bool_join(kinds: list[str]) -> bool:
        return join_kind(kinds) == "bool"

    def iterator_type_category(type_name: str) -> str:
        if type_name in {"unknown", "any"}:
            return "unknown"
        if type_name in {
            "whole_number", "decimal_number", "decimal", "fixed_decimal",
            "currency", "number", "numeric", "int64", "double",
        }:
            return "numeric"
        if type_name == "boolean":
            return "boolean"
        if type_name in {"date", "datetime", "time"}:
            return "date/time"
        return "text"

    related_path_cache: dict[tuple[str, str], tuple[Any, list[tuple[str, str, str, str]] | None]] = {}

    def related_path(source_id: str, target_id: str) -> list[tuple[str, str, str, str]] | None:
        """RELATED's way from the iterated table to the table it reads: the shortest chain of active links that lead from
        the many side to the one side (a one-to-one link leads both ways), as (table, key column, next table, next key column).
        A link switched off by CROSSFILTER(..., NONE) does not count. None when there is no way; MeasureError when two ways tie."""
        cached = related_path_cache.get((source_id, target_id))
        if cached is not None and cached[0] is relationship_definitions:
            return cached[1]
        edges: dict[str, list[tuple[str, str, str, str]]] = {}
        for relationship in relationship_definitions:
            if (
                not isinstance(relationship, dict)
                or type(relationship.get("relationship_version")) is not int
                or relationship.get("relationship_version") != 1
                or not relationship.get("is_active")
                or relationship.get("filter_direction_override") == "none"
            ):
                continue
            from_id, to_id = str(relationship.get("from_table_id", "")), str(relationship.get("to_table_id", ""))
            from_column, to_column = str(relationship.get("from_column", "")), str(relationship.get("to_column", ""))
            cardinality = relationship.get("cardinality")
            if from_id not in contexts_by_id or to_id not in contexts_by_id:
                continue
            if cardinality in {"many_to_one", "one_to_one"}:
                edges.setdefault(from_id, []).append((from_id, from_column, to_id, to_column))
            if cardinality in {"one_to_many", "one_to_one"}:
                edges.setdefault(to_id, []).append((to_id, to_column, from_id, from_column))
        frontier: dict[str, list[list[tuple[str, str, str, str]]]] = {source_id: [[]]}
        seen = {source_id}
        result: list[tuple[str, str, str, str]] | None = None
        while frontier:
            if target_id in frontier:
                if len(frontier[target_id]) > 1:
                    raise MeasureError("RELATED has more than one direct relationship or path to that related table.")
                result = frontier[target_id][0]
                break
            following: dict[str, list[list[tuple[str, str, str, str]]]] = {}
            for table_id, paths in frontier.items():
                for edge in edges.get(table_id, []):
                    if edge[2] not in seen:
                        following.setdefault(edge[2], []).extend(path + [edge] for path in paths)
            seen.update(following)
            frontier = following
        related_path_cache[(source_id, target_id)] = (relationship_definitions, result)
        return result

    def related_column_details(
        reference: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> tuple[dict[str, Any], list[tuple[str, str, str, str]], str, str, str | None]:
        """Resolve RELATED(Table[column]): the table, the chain of links to it, the column, that column's type and, for a
        table built by an expression, the header that holds the first link's key."""
        if row_context is None:
            raise MeasureError(
                "RELATED needs row context inside a supported table iterator."
            )
        if reference[0] != "reference" or not reference[1]:
            raise MeasureError(
                "RELATED needs one fully qualified column reference."
            )

        iterated_table = row_context[0]
        target_table = resolve_table_context(str(reference[1]))
        if iterated_table["id"] == target_table["id"]:
            raise MeasureError("RELATED must refer to a different related table.")
        whole_table = contexts_by_id.get(iterated_table["id"])
        if whole_table is not None and iterated_table["headers"] is not whole_table["headers"] and list(iterated_table["headers"]) != list(whole_table["headers"]):
            raise MeasureError("RELATED needs a row of the whole table; a column of it (VALUES, DISTINCT) has no relationships.")
        key_header = None
        if iterated_table.get("derived"):
            # ADDCOLUMNS, GENERATE, CROSSJOIN... keep whole rows of the loaded tables behind their lineage; SELECTCOLUMNS and
            # SUMMARIZE do not, so RELATED has no row to start from there
            lineage = iterated_table.get("lineage") or {}
            base_ids = {base["id"] for base, _column in lineage.values()}
            if not iterated_table.get("row_identity") or target_table["id"] in base_ids:
                raise MeasureError(f"RELATED has no related row to start from in {iterated_table['name']!r}.")
            paths = [(base_id, related_path(base_id, target_table["id"])) for base_id in sorted(base_ids)]
            paths = [(base_id, path) for base_id, path in paths if path]
            if len(paths) > 1:
                raise MeasureError("RELATED has more than one direct relationship or path to that related table.")
            hops = paths[0][1] if paths else None
            if hops:
                key_header = next((
                    header for header, (base, column) in lineage.items()
                    if base["id"] == hops[0][0] and column == hops[0][1]
                ), None)
                if key_header is None:
                    hops = None
        else:
            hops = related_path(iterated_table["id"], target_table["id"])
        if not hops:
            raise MeasureError(
                f"No active many-to-one relationship path connects "
                f"{iterated_table['name']!r} to {target_table['name']!r}."
            )
        target_headers = {
            str(header).casefold(): str(header)
            for header in target_table["headers"]
        }
        target_column = target_headers.get(str(reference[2]).casefold(), "")
        if not target_column:
            raise MeasureError(
                "RELATED refers to a column that is missing from its relationship or target table."
            )
        target_type = str(
            target_table.get("column_types", {}).get(target_column, "unknown")
        ).casefold()
        return target_table, hops, target_column, target_type, key_header

    def related_value(
        reference: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> Any:
        """RELATED(Table[column]) of the current row as a DAX value of the column's type; BLANK when a link finds no row."""
        target_table, hops, target_column, _, key_header = related_column_details(reference, row_context)
        assert row_context is not None
        iterated_table, row, row_index = row_context
        current_table, current_row = iterated_table, row
        if key_header is not None:  # the first link's key, taken from a typed row of an expression-built table
            current_table = contexts_by_id[hops[0][0]]
            key = row.get(key_header)
            if isinstance(key, dax_dates.DaxDateTime):
                moment = dax_dates.to_datetime(key)
                key = moment.date().isoformat() if moment.time() == time(0) else moment.isoformat()
            current_row = {hops[0][1]: key}
        try:
            for _, source_column, next_id, next_column in hops:
                next_table = evaluation_contexts_by_id.get(next_id) or contexts_by_id[next_id]
                source_type = str(current_table.get("column_types", {}).get(source_column, "text"))
                index_key = (next_table["id"], next_column, "", "", "")
                lookup = related_lookup_cache.get(index_key)
                if lookup is None:
                    next_key_type = str(next_table.get("column_types", {}).get(next_column, "text"))
                    lookup = {}
                    for candidate in next_table["rows"]:
                        lookup.setdefault(
                            _relationship_value_key(candidate.get(next_column), next_key_type), []
                        ).append(candidate)
                    related_lookup_cache[index_key] = lookup
                matches = lookup.get(_relationship_value_key(current_row.get(source_column), source_type), [])
                if len(matches) > 1:
                    raise MeasureError(
                        f"RELATED found multiple rows for {next_table['name']!r} "
                        f"at iterator row {row_index}."
                    )
                if not matches:
                    return None
                current_table, current_row = next_table, matches[0]
        except RelationshipError as exc:
            raise MeasureError(f"Could not evaluate RELATED lookup: {exc}") from exc
        return evaluate(("reference", "", target_column), (target_table, current_row, row_index), allow_text=True)

    def iterator_model_reference_category(
        expression: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> str:
        if expression[0] != "reference":
            return iterator_expression_category(expression, row_context)
        if str(expression[2]).casefold() in by_name:
            return "numeric"
        model_table = (
            resolve_table_context(expression[1])
            if expression[1]
            else evaluation_contexts_by_id.get(
                current_home_table_id, active_context
            )
        )
        headers_by_key = {
            str(header).casefold(): str(header)
            for header in model_table["headers"]
        }
        actual_column = headers_by_key.get(str(expression[2]).casefold())
        if actual_column is None:
            raise MeasureError(
                f"Column {expression[2]!r} does not exist in table {model_table['name']!r}."
            )
        column_type = model_table.get("column_types", {}).get(actual_column)
        category = iterator_type_category(
            "unknown" if column_type is None else str(column_type).casefold()
        )
        return category

    def merge_branch_categories(categories: list[str], function: str) -> str:
        """The common local type of conditional branches; blank branches take the other type."""
        concrete = {category for category in categories if category != "blank"}
        if not concrete:
            return "blank"
        if len(concrete) == 1:
            return next(iter(concrete))
        raise MeasureError(
            f"Iterator {function} comparison branches need matching local data types."
        )

    def cleared_by_column_table(table_id: str) -> list[str]:
        """Tables whose filters ALL(column) / ALLSELECTED(column) as a table value does not feel: the one-side tables of the
        column's table and the tables it is linked to by a many-to-many relationship (Critic 4, R-2). A bidirectional
        one-to-many filter still reaches the column (it decides whether the unknown member is visible)."""
        peers = {
            other for relationship in relationship_definitions
            if isinstance(relationship, dict) and relationship.get("cardinality") == "many_to_many" and relationship.get("is_active", True)
            for table, other in (
                (str(relationship.get("from_table_id", "")), str(relationship.get("to_table_id", ""))),
                (str(relationship.get("to_table_id", "")), str(relationship.get("from_table_id", ""))),
            ) if table == table_id
        }
        return [other for other in dict.fromkeys([*expanded_table_ids(table_id)[1:], *peers]) if other in evaluation_contexts_by_id]

    def has_number_branch(expression: tuple[Any, ...]) -> bool:
        """IF / SWITCH / COALESCE with a plain number as one of its results make the iterated value a number, even on rows that pick a date."""
        if expression[0] == "number":
            return True
        if expression[0] != "call":
            return False
        name, call_arguments = expression[1], expression[2]
        if name == "IF":
            results = call_arguments[1:3]
        elif name == "COALESCE":
            results = call_arguments
        elif name == "SWITCH":
            results = call_arguments[2::2] + (call_arguments[-1:] if len(call_arguments) % 2 == 0 else ())
        else:
            return False
        return any(has_number_branch(result) for result in results)

    def iterator_expression_category(
        expression: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> str:
        kind = expression[0]
        if kind == "number":
            return "numeric"
        if kind == "string":
            return "text"
        if kind == "boolean":
            return "boolean"
        if kind == "blank":
            return "blank"
        if kind == "table":
            return "table"
        if kind == "reference":
            if str(expression[2]).casefold() in by_name:
                return "numeric"
            return iterator_type_category(iterator_reference_type(expression, row_context))
        if kind == "concat":
            for operand in expression[1:]:
                iterator_expression_category(operand, row_context)
            return "text"
        if kind == "in":  # x IN {..} / (a, b) IN table: a True/False; the evaluator checks the table side
            probe = expression[1]
            for member in (probe[1] if probe[0] == "tuple" else (probe,)):
                iterator_expression_category(member, row_context)
            return "boolean"
        if kind == "var":
            try:
                held = variables[expression[1]]()
            except MeasureError:
                return "unknown"
            if held is None:
                return "blank"
            return "boolean" if isinstance(held, bool) else "text" if isinstance(held, str) else "numeric"
        if kind == "let":
            return "unknown"
        if kind in {"unary", "binary"}:
            operands = expression[2:] if kind == "binary" else (expression[2],)
            operand_categories = [iterator_expression_category(operand, row_context) for operand in operands]
            if kind == "unary" and expression[1] == "+" and operand_categories == ["boolean"]:
                return "boolean"  # live Power BI (iteration 87): unary plus leaves a True/False a True/False
            if any(
                category not in {"numeric", "blank", "boolean"}  # live Power BI (iteration 86): TRUE is 1 and FALSE is 0 in + - * and unary minus
                for category in operand_categories
            ):
                raise MeasureError(
                    "Iterator arithmetic comparisons need numeric operands."
                )
            return "numeric"
        if kind == "logical":
            operand_categories = (
                iterator_expression_category(expression[2], row_context),
                iterator_expression_category(expression[3], row_context),
            )
            if any(
                category not in {"boolean", "blank", "numeric"}  # live Power BI (iteration 87): a number is True unless it is zero
                for category in operand_categories
            ):
                raise MeasureError(
                    "Logical iterator conditions need Boolean operands."
                )
            return "boolean"
        if kind == "comparison":
            iterator_comparison_operand_category(expression, row_context)
            return "boolean"
        if kind == "call":
            function = expression[1]
            if function == "RELATED":
                return iterator_type_category(related_column_details(expression[2][0], row_context)[3])
            if function in _TYPED_ARITY:
                for argument in expression[2]:
                    iterator_expression_category(argument, row_context)
                return _TYPED_RESULT_CATEGORY.get(function, "numeric")
            if function == "CALCULATE" and expression[2]:
                return iterator_expression_category(expression[2][0], row_context)
            if function in {"LOOKUPVALUE", "SELECTEDVALUE"} and expression[2] and expression[2][0][0] == "reference":
                # typed as the column it reads; a SELECTEDVALUE alternate of another type makes it a Variant, which is not typed here
                column_category = iterator_model_reference_category(expression[2][0], row_context)
                if function == "SELECTEDVALUE" and len(expression[2]) == 2 and iterator_expression_category(expression[2][1], row_context) not in {column_category, "blank"}:
                    return "unknown"
                return column_category
            if function in _COLUMN_SCALAR_ARITY:
                return "boolean" if function == "HASONEVALUE" else "unknown"
            if function in _BOOLEAN_INFO_CALLS:
                return "boolean"  # live Power BI (iteration 87): a True/False whatever its arguments (the evaluator checks those)
            if function in dax_math.STAT_COLUMN_FUNCTIONS or function in dax_math.STAT_PERCENTILE_COLUMN:
                return "numeric"
            if function == "COUNTROWS" and len(expression[2]) == 1 and (
                expression[2][0][0] == "tableconstructor" or (expression[2][0][0] == "call" and expression[2][0][1] in _TABLE_BUILDING_CALLS)
            ):
                return "numeric"  # the rows of a table built from constants and columns; FILTER and the like are validated further down
            if function == "CONCATENATEX":
                return "text"
            if function in {"RANKX", "RANK.EQ", "RANK", "ROWNUMBER", "XNPV"}:
                return "numeric"
            if function == "COALESCE" and expression[2]:
                return iterator_expression_category(expression[2][0], row_context)
            if function in {"EARLIER", "EARLIEST"}:
                # typed by the column it reads, so EARLIER(numeric column) can sit inside arithmetic (Power BI accepts it);
                # a text column or any column whose type cannot be resolved stays "unknown"/"text" and is refused there
                earlier_reference = expression[2][0] if expression[2] else None
                if earlier_reference is not None and earlier_reference[0] == "reference":
                    # the row being validated is not on row_stack yet (MAXX/MINX/COUNTX validate a sample row first)
                    for held_frame in ([row_context] if row_context is not None else []) + list(reversed(row_stack)):
                        try:
                            held_type = iterator_reference_type(earlier_reference, held_frame)
                        except MeasureError:
                            continue
                        return iterator_type_category(held_type)
                return "unknown"
            if function in {"ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLSELECTED", "CALCULATETABLE"}:
                return "table"
            if function == "FILTER" and len(expression[2]) == 2:
                iterator_expression_category(expression[2][0], row_context)
                predicate_category = iterator_expression_category(
                    expression[2][1], row_context
                )
                if predicate_category != "boolean":
                    raise MeasureError(
                        "Iterator FILTER comparisons need a logical row predicate."
                    )
                return "table"
            if function in {"AND", "OR", "NOT"}:
                operand_categories = tuple(
                    iterator_expression_category(argument, row_context)
                    for argument in expression[2]
                )
                if any(
                    category not in {"boolean", "blank", "numeric"}
                    for category in operand_categories
                ):
                    raise MeasureError(
                        "Logical iterator conditions need Boolean operands."
                    )
                return "boolean"
            if function == "IF" and len(expression[2]) in {2, 3}:
                condition_category = iterator_expression_category(
                    expression[2][0], row_context
                )
                if condition_category not in {"boolean", "blank", "numeric"}:  # a number is True unless it is zero (live Power BI, iteration 87)
                    raise MeasureError(
                        "Iterator IF conditions need a Boolean expression."
                    )
                branch_categories = [
                    iterator_expression_category(branch, row_context)
                    for branch in expression[2][1:]
                ]
                return merge_branch_categories(branch_categories, "IF")
            if function == "ISBLANK" and len(expression[2]) == 1:
                iterator_expression_category(expression[2][0], row_context)
                return "boolean"
            if function == "IFERROR" and len(expression[2]) == 2:
                return merge_branch_categories([
                    iterator_expression_category(argument, row_context)
                    for argument in expression[2]
                ], "IFERROR")
            if function == "SWITCH" and len(expression[2]) >= 3:
                subject_category = iterator_expression_category(expression[2][0], row_context)
                remaining = list(expression[2][1:])
                fallback = remaining.pop() if len(remaining) % 2 else None
                for candidate in remaining[::2]:
                    candidate_category = iterator_expression_category(candidate, row_context)
                    if "blank" not in {subject_category, candidate_category} and subject_category != candidate_category:
                        raise MeasureError(
                            "Iterator SWITCH values need the same local data type as the expression."
                        )
                result_arguments = remaining[1::2] + ([] if fallback is None else [fallback])
                return merge_branch_categories([
                    iterator_expression_category(argument, row_context)
                    for argument in result_arguments
                ], "SWITCH")
            if function in {
                "DATESYTD", "DATESQTD", "DATESMTD", "DATESBETWEEN",
                "DATESINPERIOD", "PREVIOUSYEAR", "PREVIOUSQUARTER",
                "PREVIOUSMONTH", "PREVIOUSDAY", "NEXTYEAR", "NEXTQUARTER",
                "NEXTMONTH", "NEXTDAY", "PARALLELPERIOD", "DATEADD",
                "SAMEPERIODLASTYEAR",
            }:
                for argument in expression[2]:
                    iterator_expression_category(argument, row_context)
                return "table"
            if function in _ALL_ITERATORS:
                pushed_outer = row_context is not None and (not row_stack or row_stack[-1][1] is not row_context[1])
                if pushed_outer:
                    row_stack.append(row_context)  # type: ignore[arg-type]  # the table of a nested iterator may read a column of this row (iteration 88)
                try:
                    iterated_table, iteration_rows = table_argument_value(expression[2][0])
                finally:
                    if pushed_outer:
                        row_stack.pop()
                validation_row = iteration_rows[0] if iteration_rows else {}
                result_category = iterator_expression_category(
                    expression[2][1], (iterated_table, validation_row, 1)
                )
                extreme = function in {"MAXX", "MINX"}
                if (
                    function in _ALL_ITERATORS - {"COUNTX", "COUNTAX"}
                    and result_category not in ({"numeric", "blank", "date/time", "text"} if extreme else {"numeric", "blank"})
                ):
                    raise MeasureError(
                        f"Iterator {function} expression needs a numeric result."
                    )
                return result_category if extreme and result_category in {"date/time", "text"} else "numeric"
            if function in {
                "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA",
                "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "COUNTROWS",
                "MEDIAN", "PRODUCT", "COUNTBLANK",
                "DIVIDE", "ABS", "ROUND", *_SCALAR_MATH_ARITY,
                "TOTALYTD", "TOTALQTD", "TOTALMTD",
            }:
                numeric_argument_indexes: set[int] = set()
                date_extreme = False
                if function in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "ABS", "MEDIAN", "PRODUCT"}:
                    numeric_argument_indexes.add(0)
                elif function == "DIVIDE":
                    numeric_argument_indexes.update(range(len(expression[2])))
                elif function == "ROUND" or function in _SCALAR_MATH_ARITY:
                    numeric_argument_indexes.update(range(len(expression[2])))
                elif function in {"TOTALYTD", "TOTALQTD", "TOTALMTD"}:
                    numeric_argument_indexes.add(0)
                for argument_index, argument in enumerate(expression[2]):
                    if argument[0] == "table" or (function == "COUNTROWS" and argument[0] == "table_call"):
                        continue
                    aggregate_column = (
                        function in {
                            "SUM", "AVERAGE", "MIN", "MAX", "COUNT",
                            "COUNTA", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK",
                            "MEDIAN", "PRODUCT", "COUNTBLANK",
                        }
                        and argument_index == 0
                        and argument[0] == "reference"
                    )
                    argument_category = (
                        iterator_model_reference_category(argument, row_context)
                        if aggregate_column
                        else iterator_expression_category(argument, row_context)
                    )
                    if (
                        argument_index in numeric_argument_indexes
                        and argument_category not in {"numeric", "blank"}
                        and not (function in {"ABS", "INT"} and argument_category == "boolean")  # live Power BI: ABS(TRUE) and INT(TRUE) are 1
                    ):
                        if function in {"MIN", "MAX"} and argument_category == "date/time" and aggregate_column:
                            date_extreme = True  # the latest / earliest date of a column is a date (live Power BI)
                            continue
                        if function == "AVERAGE" and argument_category == "date/time" and aggregate_column:
                            continue  # the average of a date column is a plain number
                        raise MeasureError(
                            f"Iterator {function} argument {argument_index + 1} needs a numeric expression."
                        )
                return "date/time" if date_extreme else "numeric"
        raise MeasureError(
            "Iterator comparison expression has an unsupported or unverifiable local data type."
        )

    def iterator_comparison_operand_category(
        comparison: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> str:
        operator, left_expression, right_expression = comparison[1:4]  # a 5th item marks an IN comparison
        variant = row_context[0].get("variant_columns") if row_context is not None else None
        if variant and any(
            str(reference[2]).casefold() in variant for operand in (left_expression, right_expression)
            for reference in _iter_reference_nodes(operand) if len(reference) > 2
        ):
            raise MeasureError("A comparison with a column whose branches have different types is not supported in the local engine.")
        left_category = iterator_expression_category(left_expression, row_context)
        right_category = iterator_expression_category(right_expression, row_context)
        if left_expression == ("blank",) and right_expression == ("blank",):
            return "numeric"  # BLANK() = BLANK() is True (live Power BI, iteration 87)
        if left_category == "date/time":  # dates are compared as day numbers
            left_category = "numeric"
        if right_category == "date/time":
            right_category = "numeric"
        if left_category in {"blank", "unknown"}:
            left_category = right_category
        if right_category in {"blank", "unknown"}:
            right_category = left_category
        if left_category in {"blank", "unknown"} or right_category in {"blank", "unknown"}:
            raise MeasureError(
                "Iterator comparison operands have unverifiable local data types."
            )
        if left_category != right_category:
            raise MeasureError(
                "Iterator comparisons need matching local data types."
            )
        return left_category

    numdate_nodes: list[bool] = []
    variant_coalesce_arguments: list[tuple[Any, ...]] = []

    def merge_value_types(parts: list[tuple[str, bool]]) -> tuple[str, bool]:
        """The static type of an IF / SWITCH / IFERROR / COALESCE whose result branches have these (type, is the literal BLANK()) types.

        Live Power BI (iteration 87): a literal BLANK() takes the type of the other branches, but an IF / SWITCH whose branches are all blank
        is itself typed as a number.  Branches that are all numbers, or all dates, keep that type; numbers beside dates make a number;
        any other mix (text beside a number, a True/False beside a number or text, text beside a date ...) makes a Variant."""
        kinds: set[str] = set()
        for value_type, literal_blank in parts:
            if value_type == "blank":
                if literal_blank:
                    continue
                value_type = "number"
            kinds.add(value_type)
        if not kinds:
            return "blank", False
        if len(kinds) == 1:
            return next(iter(kinds)), False
        if kinds <= {"number", "date", "numdate"}:
            numdate_nodes.append(True)
            return "numdate", False  # a number type that includes dates: its dates are plain numbers
        return "variant", False

    def body_value_type(expression: tuple[Any, ...], row_context: tuple[dict[str, Any], dict[str, Any], int] | None) -> tuple[str, bool]:
        """Static type of an iterator body that is an IF / SWITCH / IFERROR / COALESCE: number, numdate, date, text, bool, blank or variant
        (the second item says the expression is the literal BLANK()).  Raises MeasureError when a branch cannot be typed with certainty."""
        if expression == ("blank",):
            return "blank", True
        if expression[0] == "call" and expression[1] in {"IF", "SWITCH", "IFERROR", "COALESCE"}:
            name, args = expression[1], expression[2]
            if name == "IF" and len(args) in {2, 3}:
                if iterator_expression_category(args[0], row_context) not in {"boolean", "blank", "numeric"}:
                    raise MeasureError("Iterator IF conditions need a Boolean expression.")
                parts = [body_value_type(branch, row_context) for branch in args[1:]]
                if len(args) == 2:
                    parts.append(("blank", True))
                return merge_value_types(parts)
            if name == "IFERROR" and len(args) == 2:
                return merge_value_types([body_value_type(branch, row_context) for branch in args])
            if name == "COALESCE" and len(args) >= 2:
                parts = [body_value_type(branch, row_context) for branch in args]
                accumulated = parts[-1]
                for part in reversed(parts[:-1]):  # live Power BI (iteration 87): COALESCE(a, b, c) is typed as COALESCE(a, COALESCE(b, c))
                    accumulated = merge_value_types([part, accumulated])
                if accumulated[0] in {"variant", "numdate"}:
                    variant_coalesce_arguments.extend(args[1:])
                return accumulated
            if name == "SWITCH" and len(args) >= 3:
                subject_category = iterator_expression_category(args[0], row_context)
                remaining = list(args[1:])
                fallback = remaining.pop() if len(remaining) % 2 else None
                for candidate in remaining[::2]:
                    candidate_category = iterator_expression_category(candidate, row_context)
                    if "blank" not in {subject_category, candidate_category} and subject_category != candidate_category:
                        raise MeasureError("Iterator SWITCH values need the same local data type as the expression.")
                accumulated = body_value_type(fallback, row_context) if fallback is not None else ("blank", True)
                for result in reversed(remaining[1::2]):  # Power BI types SWITCH as IFs nested from the right
                    accumulated = merge_value_types([body_value_type(result, row_context), accumulated])
                return accumulated
            raise MeasureError(f"{name} with this number of arguments is not typed by the local engine.")
        if expression[0] == "reference":
            variant = row_context[0].get("variant_columns") if row_context is not None else None
            if variant and str(expression[2]).casefold() in variant:
                if str(expression[2]).casefold() in row_context[0].get("variant_date_columns", ()):
                    numdate_nodes.append(True)
                return "variant", False
        if expression[0] == "call" and (
            expression[1] == "SELECTEDVALUE" or expression[1] in {"MIN", "MAX"}
        ) and len(expression[2]) == 1 and expression[2][0][0] == "reference":
            # typed as its column (SELECTEDVALUE is BLANK() when several values are selected; the latest / earliest / largest / smallest of a column)
            category = iterator_model_reference_category(expression[2][0], row_context)
        else:
            category = iterator_expression_category(expression, row_context)
        if category == "blank" and expression[0] == "call":
            return "blank", False  # CALCULATE(BLANK()) and the like: a blank that is computed, not the literal
        mapped = {"numeric": "number", "text": "text", "boolean": "bool", "date/time": "date"}.get(category)
        if mapped is None:
            raise MeasureError("The type of this branch is not known to the local engine.")
        return mapped, False

    def iterator_body_kind(expression: tuple[Any, ...], row_context: tuple[dict[str, Any], dict[str, Any], int] | None) -> str | None:
        """"variant" / "numdate" for an iterator body whose IF / SWITCH / IFERROR / COALESCE branches differ in type (or that reads a
        Variant column), the type itself ("number", "date", "text", "bool", "blank") for any other conditional, None when it is not one or its
        type cannot be established (the older rules apply)."""
        if expression[0] == "reference":
            variant = row_context[0].get("variant_columns") if row_context is not None else None
            if variant and str(expression[2]).casefold() in variant:
                return "variant_dates" if str(expression[2]).casefold() in row_context[0].get("variant_date_columns", ()) else "variant"
            return None
        if expression[0] != "call" or expression[1] not in {"IF", "SWITCH", "IFERROR", "COALESCE"}:
            return None
        numdate_nodes.clear()
        variant_coalesce_arguments.clear()
        try:
            value_type, _ = body_value_type(expression, row_context)
        except MeasureError:
            if _spine_has_coalesce(expression):
                # the older rules type a COALESCE by its first argument only, which gives wrong answers when the others differ in type
                raise MeasureError("COALESCE with branches whose types the local engine cannot establish is not supported in iterator bodies.")
            return None
        if variant_coalesce_arguments and not all(_cannot_raise(argument) for argument in variant_coalesce_arguments):
            # live Power BI: a COALESCE of mixed types evaluates all its arguments, so an error in a later one (VALUE("East")) is not skipped
            raise MeasureError("COALESCE of mixed types with an argument that can fail is not supported in the local engine.")
        if value_type == "variant" and numdate_nodes:
            kind = "variant_dates"  # live Power BI: a number-and-date branch inside a Variant turns its dates into plain numbers first
        else:
            kind = value_type
        return kind

    def evaluate_with_date_values(
        expression: tuple[Any, ...],
        date_table: dict[str, Any],
        date_column: str,
        selected_dates: set[date],
    ) -> Decimal | None:
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
        # live Power BI: applying a date set to a date key column first removes the other outer filters of its expanded table
        wiped_ids = set(expanded_table_ids(date_table["id"])) if is_date_key(date_table, date_column) else set()
        for table_id, context in evaluation_contexts_by_id.items():
            updated = dict(context)
            if table_id in wiped_ids:
                for state in ("filter_rows", "filter_table_rows", "filter_shapes", "filter_column_extra"):
                    updated.pop(state, None)
                updated["filter_column_rows"] = {}
                updated["filter_column_blank_allowed"] = {}
                updated["filter_context_complete"] = True
                context = updated
            if table_id == date_table["id"]:
                if "filter_table_rows" in context or _context_shapes(context):
                    # the date column drops out of the FILTER rows; its other columns keep constraining by the rows' values
                    column_rows = dict(context.get("filter_column_rows", {}))
                    clear_columns_from_shapes(updated, {date_column.casefold()}, column_rows)
                    updated["filter_column_rows"] = column_rows
                    context = updated
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
                        column: _frozen(indexes)
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
                (evaluation_filter_ids - wiped_ids) | {date_table["id"]},
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
        evaluation_filter_ids = (evaluation_filter_ids - wiped_ids) | {date_table["id"]}
        rows_by_table_id = time_rows_by_table_id
        try:
            return evaluate(expression)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids

    conjunct_constants: dict[Any, Any] = {}
    filter_constants: dict[tuple[int, Any], Any] = {}

    def filter_constant(node: tuple[Any, ...]) -> Any:
        """The scalar side of a filter, evaluated once in the context the filter is written in."""
        kind = node[0]
        if kind in {"number", "string", "boolean"}:
            return node[1]
        if kind in {"blank", "blank_comment"}:
            return None
        # the value depends on the filter context, the enclosing row contexts (EARLIER) and the VARs in scope
        frames = tuple(frame[1] for frame in row_stack)
        bound = tuple(variables.values())
        cache_key = (id(node), current_context, tuple(id(frame) for frame in frames), tuple(id(item) for item in bound))
        cached = filter_constants.get(cache_key)
        if cached is None:
            row_stack.append(({"headers": [], "derived": True}, {}, 0))  # the filter's own row context
            try:
                value = evaluate(node, None, allow_text=True, allow_boolean=True)
            finally:
                row_stack.pop()
            cached = filter_constants[cache_key] = (value, frames, bound)  # the tuples keep their ids from being reused
        return cached[0]

    def typed_filter_value(
        value: Any,
        column_type: str,
        column: str,
        row_index: int | None = None,
    ) -> Any:
        """Convert a row value or scalar literal using the column's saved type."""
        _reject_power_query_error(value, column, row_index)
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
            # The model compares stored text case-insensitively for ASCII letters.
            return "" if value is None else ascii_fold(str(value))
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
                and not is_literal
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
        if column_type in {"date", "datetime"} and is_literal and isinstance(value, dax_dates.DaxDateTime):
            moment = dax_dates.to_datetime(value)
            return moment.date() if column_type == "date" else moment
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
            if (
                _contains_function_call(literal, "CALCULATE")
                or _contains_function_call(literal, "CALCULATETABLE")
                or _contains_function_call(literal, "EARLIER")
                or _contains_function_call(literal, "EARLIEST")
                or any(not item[1] and item[2].casefold() in by_name for item in _iter_reference_nodes(literal))
            ):
                # CALCULATE, CALCULATETABLE (or a measure) in a FILTER predicate transitions each filtered row, and EARLIER inside it
                # reads the row being filtered: there is no single constant
                raise MeasureError("This FILTER value depends on the row being filtered.")
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
        if node[0] != "call" or node[1] not in {"AND", "OR", "NOT"}:
            raise MeasureError("This FILTER predicate is evaluated row by row.")
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
    ) -> Decimal | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids, eff_layers, eff_touched
        filters_by_column: dict[
            tuple[str, str], list[tuple[frozenset[int], bool, bool]]
        ] = {}
        targets_by_key: dict[
            tuple[str, str], tuple[dict[str, Any], str]
        ] = {}
        explicit_here: list[tuple[str, str, bool, Any, dict[str, Any]]] = []
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
            if "filter_table_rows" in target_context or _context_shapes(target_context):
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
        for key in (extra_date_filters or {}):  # live Power BI: a date set on a date key first removes the table's other outer filters
            key_context, key_column = targets_by_key[key]
            if not is_date_key(key_context, key_column):
                continue
            for wiped_id in expanded_table_ids(key_context["id"]):
                wiped = updated_by_id.get(wiped_id)
                if wiped is None:
                    continue
                for state in ("filter_rows", "filter_table_rows", "filter_shapes", "filter_column_extra"):
                    wiped.pop(state, None)
                wiped["filter_column_rows"] = {}
                wiped["filter_column_blank_allowed"] = {}
                wiped["filter_context_complete"] = True
                updated_filter_roots.discard(wiped_id)
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
            explicit_here.append((table_id, actual_column, keep, new_rows, target_context))

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
                column: _frozen(indexes)
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
        saved_layers, saved_touched = eff_layers, eff_touched
        eff_touched = eff_touched | {(table_id, column.casefold()) for table_id, column, _keep, _rows, _ctx in explicit_here}
        for table_id, column, keep, rows_allowed, filter_context in explicit_here:  # an explicit filter replaces the shadow on its column
            if not keep:
                eff_layers = project_layers(eff_layers, table_id, [column])
            else:
                eff_layers = (*eff_layers, _Shadow(table_id, (column,), lambda column=column, rows_allowed=rows_allowed, filter_context=filter_context: frozenset(
                    row_key([typed_cell(filter_context, column, filter_context["rows"][index].get(column))]) for index in rows_allowed)))
        try:
            return evaluate(expression)
        finally:
            eff_layers, eff_touched = saved_layers, saved_touched
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids

    def validate_allselected_modifier(modifier: tuple[Any, ...]) -> None:
        """Resolve ALLSELECTED targets in the bounded local model."""
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

    def allselected_matches_visual_axis(
        modifier: tuple[Any, ...],
    ) -> bool:
        """Match the one qualified chart-axis column supported by this path."""
        if visual_axis_context is None:
            return False
        arguments = modifier[2]
        if len(arguments) != 1 or arguments[0][0] != "reference":
            return False
        context, column = resolve_table(
            arguments[0][1], arguments[0][2]
        )
        return (
            context["id"] == visual_axis_context.table_id
            and column.casefold() == visual_axis_context.column.casefold()
        )

    def evaluate_with_allselected(
        expression: tuple[Any, ...],
        modifier: tuple[Any, ...],
        filter_arguments: tuple[tuple[Any, ...], ...] = (),
    ) -> Decimal | None:
        """Evaluate ALLSELECTED with saved selections and the bounded chart axis."""
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        validate_allselected_modifier(modifier)
        if allselected_matches_visual_axis(modifier):
            (
                selected_contexts,
                selected_filter_ids,
                selected_rows_by_id,
            ) = rows_after_restoring_visual_axis()
            previous_rows = rows_by_table_id
            previous_context = current_context
            previous_contexts = evaluation_contexts_by_id
            previous_filter_ids = evaluation_filter_ids
            context_sequence += 1
            current_context = context_sequence
            evaluation_contexts_by_id = selected_contexts
            evaluation_filter_ids = selected_filter_ids
            rows_by_table_id = selected_rows_by_id
            try:
                if filter_arguments:
                    if (
                        len(filter_arguments) == 1
                        and filter_arguments[0][0] == "call"
                        and filter_arguments[0][1] == "FILTER"
                    ):
                        return evaluate_with_table_filter(
                            expression, filter_arguments[0]
                        )
                    return evaluate_with_boolean_filters(
                        expression, filter_arguments
                    )
                return evaluate(expression)
            finally:
                rows_by_table_id = previous_rows
                current_context = previous_context
                evaluation_contexts_by_id = previous_contexts
                evaluation_filter_ids = previous_filter_ids
        # The local report evaluator has saved report/page/visual selections and
        # relationship roots. Other ALLSELECTED forms keep the current context.
        if eff_active():
            def with_the_other_filters() -> Any:
                if filter_arguments:
                    if len(filter_arguments) == 1 and filter_arguments[0][0] == "call" and filter_arguments[0][1] == "FILTER":
                        return evaluate_with_table_filter(expression, filter_arguments[0])
                    return evaluate_with_boolean_filters(expression, filter_arguments)
                return evaluate(expression)

            return evaluate_with_filter_clear(("thunk", with_the_other_filters), modifier, "ALLSELECTED")
        if filter_arguments:
            if (
                len(filter_arguments) == 1
                and filter_arguments[0][0] == "call"
                and filter_arguments[0][1] == "FILTER"
            ):
                return evaluate_with_table_filter(expression, filter_arguments[0])
            return evaluate_with_boolean_filters(expression, filter_arguments)
        return evaluate(expression)

    def evaluate_with_userelationships(
        expression: tuple[Any, ...],
        modifiers: tuple[tuple[Any, ...], ...],
        filter_arguments: tuple[tuple[Any, ...], ...] = (),
        extra_date_filters: dict[tuple[str, str], tuple[dict, str, frozenset[int]]] | None = None,
    ) -> Decimal | None:
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
            if relationship.get("cardinality") == "one_to_one" and relationship.get("is_active") and any(
                one_to_one_unmatched(table_id)[0] or one_to_one_unmatched(table_id)[1] for table_id in (left_context["id"], right_context["id"])
            ):
                # live Power BI (iteration 84, critic; 15 of 1,033 fresh ZM probes): USERELATIONSHIP over a one-to-one relationship whose tables
                # have unmatched rows moves the blank members in a way not modelled here (COUNTROWS(W) under U[K]<>"k2" is 3, ours 4)
                raise MeasureError("USERELATIONSHIP over a one-to-one relationship with unmatched rows is not supported in the local engine.")
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
            if filter_arguments or extra_date_filters:
                return evaluate_with_boolean_filters(
                    expression, filter_arguments, extra_date_filters
                )
            return evaluate(expression)
        finally:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            current_context = previous_context
            unknown_member_ids = previous_unknown_members

    def evaluate_with_crossfilters(
        expression: tuple[Any, ...],
        modifiers: tuple[tuple[Any, ...], ...],
        filter_arguments: tuple[tuple[Any, ...], ...] = (),
        extra_date_filters: dict[tuple[str, str], tuple[dict, str, frozenset[int]]] | None = None,
    ) -> Decimal | None:
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
            if previous_index is not None:
                raise MeasureError(  # live Power BI: a relationship's direction cannot be specified more than once within a single CALCULATE
                    "One CALCULATE call cannot target the same CROSSFILTER link twice or competing links between the same two tables."
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
        except (RelationshipError, DecimalException) as exc:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            unknown_member_ids = previous_unknown_members
            raise MeasureError(f"Could not apply CROSSFILTER: {exc}") from exc

        context_sequence += 1
        current_context = context_sequence
        try:
            if filter_arguments or extra_date_filters:
                return evaluate_with_boolean_filters(
                    expression, filter_arguments, extra_date_filters
                )
            return evaluate(expression)
        finally:
            relationship_definitions = previous_relationships
            rows_by_table_id = previous_rows
            current_context = previous_context
            unknown_member_ids = previous_unknown_members

    def table_filter_matching_indexes(
        filter_node: tuple[Any, ...],
    ) -> tuple[str, set[int]]:
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

        # Capture the FILTER input from the current context before any clear
        # modifier changes the visible rows.
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
        return table_id, matching_indexes

    def allexcept_kept_columns(arguments: tuple[Any, ...]) -> dict[str, set[str]]:
        """table id -> casefolded columns ALLEXCEPT keeps (a bare table keeps all of its columns)."""
        kept: dict[str, set[str]] = {}
        for reference in arguments[1:]:
            if reference[0] == "table":
                context = resolve_table_context(str(reference[1]))
                kept.setdefault(context["id"], set()).update(h.casefold() for h in context["headers"])
                continue
            context, actual_column = resolve_table(reference[1], reference[2])
            kept.setdefault(context["id"], set()).add(actual_column.casefold())
        return kept

    def one_side_links(table_id: str, include_inactive: bool = False) -> list[tuple[str, str, str]]:
        """(table on the one side, column here, column there) for every active relationship that lets a row of this table reach
        a row of another table: its many-to-one parents and, both ways, its one-to-one partners (live Power BI)."""
        links: list[tuple[str, str, str]] = []
        for relationship in relationship_definitions:
            if (
                not isinstance(relationship, dict)
                or relationship.get("relationship_version") != 1
                or not (relationship.get("is_active") or include_inactive)
                or relationship.get("filter_direction_override") == "none"  # live Power BI: CROSSFILTER(.., NONE) also stops a row context from reaching across
            ):
                continue
            cardinality = relationship.get("cardinality")
            from_id, to_id = str(relationship.get("from_table_id", "")), str(relationship.get("to_table_id", ""))
            from_column, to_column = str(relationship.get("from_column", "")), str(relationship.get("to_column", ""))
            if cardinality in {"many_to_one", "one_to_one"} and from_id == table_id:
                links.append((to_id, from_column, to_column))
            elif cardinality in {"one_to_many", "one_to_one"} and to_id == table_id:
                links.append((from_id, to_column, from_column))
        return links

    def expanded_table_ids(table_id: str, include_inactive: bool = False) -> list[str]:
        """The table plus every table on its one side reachable through active relationships (live Power BI: ALL(Fact) clears Dim).

        tools/parity: tests/fixtures_fact_all.json. Read from the relationships of the enclosing context, so a USERELATIONSHIP
        of an outer CALCULATE counts and one in the same CALCULATE does not."""
        found = [table_id]
        queue = [table_id]
        while queue:
            current = queue.pop()
            for one, _here, _there in one_side_links(current, include_inactive):
                if one in evaluation_contexts_by_id and one not in found:
                    found.append(one)
                    queue.append(one)
        return found

    def referenced_one_side_rows(table_id: str, allowed: Iterable[int]) -> dict[str, frozenset[int] | None]:
        """The rows of every table on the one side of table_id that the given rows of it point at (a table filter over the
        whole table also filters the tables it expands to: live Power BI, CALCULATE(COUNTROWS(Dim), FILTER(ALL(Fact), ...))).
        None for a table that stays unrestricted: some row points past it (a key with no partner belongs to the unknown
        member, which stays in the expanded table) or every row of it is pointed at."""
        reached: dict[str, frozenset[int] | None] = {}
        # (table, listed rows or None while unrestricted, the real rows the filtered rows point at).  A one-to-one partner is reached through
        # the real rows only, whether or not an unmatched key keeps the table's own blank member (live Power BI, iteration 84 testing agent:
        # CALCULATE(COUNTROWS(W), FILTER(F, F[Id]<=5)) is 3 and FILTER(F, F[Id]=6) is BLANK: the partner's orphan row is never reached)
        own_blank = bool(getattr(allowed, "blank", False))  # the filter lists the table's own blank member (ALL(U)): its partner stays whole
        allowed = list(allowed)
        queue: list[tuple[str, Iterable[int] | None, Iterable[int] | None, bool]] = [(table_id, allowed, allowed, False)]
        while queue:
            current_id, rows_here, real_rows, blank_up = queue.pop()
            current = contexts_by_id.get(current_id)
            if current is None:
                continue
            for one_id, here_column, there_column in one_side_links(current_id):
                one_context = contexts_by_id.get(one_id)
                if one_context is None or one_id == table_id or one_id in reached:
                    continue
                peer = any(
                    isinstance(item, dict) and item.get("is_active") and item.get("cardinality") == "one_to_one"
                    and {str(item.get("from_table_id")), str(item.get("to_table_id"))} == {current_id, one_id}
                    for item in relationship_definitions
                )
                source_rows = real_rows if peer else rows_here
                if peer and own_blank and current_id == table_id:
                    source_rows = None
                if source_rows is None:
                    reached[one_id] = None
                    queue.append((one_id, None, None, True))
                    continue
                index = one_side_value_index(one_context, there_column)
                found: set[int] = set()
                unmatched = False
                for position in source_rows:
                    matches = index.get(cell_key(typed_cell(current, here_column, current["rows"][position].get(here_column))))
                    if matches:
                        found |= matches
                    else:
                        unmatched = True
                # a table every row of which is pointed at needs no filter (nothing to narrow), like one with an unknown member
                if peer:
                    full = len(found) == len(one_context["rows"])
                    # the partner's blank member is listed when a real row has no partner or the table before it listed its own
                    kept = BlankSet(found, unmatched or blank_up, unmatched and not blank_up) if unmatched or blank_up else frozenset(found)
                    reached[one_id] = None if full else kept
                    queue.append((one_id, None if full else kept, frozenset(found), bool(getattr(kept, "blank", False))))
                else:
                    reached[one_id] = None if unmatched or len(found) == len(one_context["rows"]) else frozenset(found)
                    queue.append((one_id, None if unmatched else frozenset(found), frozenset(found), unmatched))
        return reached

    def narrow_one_side_tables(
        updated_by_id: dict[str, dict[str, Any]], updated_filter_roots: set[str], table_id: str, matching_indexes: Iterable[int]
    ) -> None:
        """A table filter over a whole table also filters the tables on its one side to the rows the filtered rows point at, and
        replaces whatever filtered them before (live Power BI: CALCULATE(CALCULATE(n, Dim[Cat]="A"), FILTER(ALL(Fact), ...)))."""
        for one_id, one_rows in referenced_one_side_rows(table_id, matching_indexes).items():
            target = updated_by_id.get(one_id)
            if target is None:
                continue
            if one_rows is None:  # the unknown member stays: whatever filtered this table is replaced by nothing
                for state in ("filter_rows", "filter_table_rows", "filter_shapes", "filter_column_extra"):
                    target.pop(state, None)
                target["filter_column_rows"] = {}
                target["filter_column_blank_allowed"] = {}
                target["filter_context_complete"] = True
                updated_filter_roots.discard(one_id)
                continue
            target["filter_rows"] = [row for position, row in enumerate(target["rows"]) if position in one_rows]
            if isinstance(one_rows, BlankSet) and one_rows.blank:
                # a one-to-one partner of a row without a partner lists its own blank member (live Power BI: the partner's orphan rows stay
                # visible) and is filtered column by column, so a later filter on one column replaces only that column
                for state in ("filter_table_rows", "filter_shapes", "filter_column_extra"):
                    target.pop(state, None)
                target["filter_column_rows"] = {header: one_rows for header in target["headers"]}
                target["filter_column_blank_allowed"] = {header: True for header in target["headers"]}
                target["filter_context_complete"] = True
                updated_filter_roots.add(one_id)
                continue
            target["filter_table_rows"] = frozenset(one_rows)  # kept as a set of whole rows, like the filtered table itself
            target.pop("filter_shapes", None)
            target.pop("filter_column_extra", None)
            target["filter_column_rows"] = {}
            target["filter_column_blank_allowed"] = {}
            target["filter_context_complete"] = False
            updated_filter_roots.add(one_id)

    def evaluate_with_filter_clear(
        expression: tuple[Any, ...],
        modifier: tuple[Any, ...],
        function: str,
        *rest: Any,
        **named: Any,
    ) -> Any:
        """ALL / REMOVEFILTERS / ALLEXCEPT also strip the cleared columns from the iterator shadows and the transition."""
        nonlocal eff_layers, eff_suppressed, eff_transition, eff_touched
        arguments = modifier[2]
        dropped: dict[str, frozenset[str] | None] = {}  # table id -> casefolded columns, None = every column
        try:
            if True:
                if not arguments:
                    dropped = {table_id: None for table_id in evaluation_contexts_by_id}
                elif function == "ALLEXCEPT":
                    table = resolve_table_context(str(arguments[0][1]))
                    kept = allexcept_kept_columns(arguments)
                    dropped = {
                        table_id: frozenset(h.casefold() for h in evaluation_contexts_by_id[table_id]["headers"]) - kept.get(table_id, set())
                        for table_id in expanded_table_ids(table["id"])
                    }
                elif arguments[0][0] == "table":
                    table_id = resolve_table_context(str(arguments[0][1]))["id"]
                    dropped = {related: None for related in expanded_table_ids(table_id)}
                else:
                    for reference in arguments:
                        context, column = resolve_table(reference[1], reference[2])
                        dropped[context["id"]] = dropped.get(context["id"], frozenset()) | {column.casefold()}
        except MeasureError:
            dropped = {}
        if not dropped:
            return evaluate_with_filter_clear_core(expression, modifier, function, *rest, **named)
        if function == "ALLSELECTED" and eff_active():
            # CALCULATE(e, ALLSELECTED(X)): what X holds of the context transition or of an outer filter a shadow replaced is
            # cleared, then every shadow touching X is put back whole (outer and explicit filters on X stay)
            to_clear: dict[str, list[str]] = {}
            restore: dict[str, dict[str, Any]] = {}  # table -> column -> the outer filter a transition covered up
            for table_id, wanted_columns in dropped.items():
                headers = evaluation_contexts_by_id[table_id]["headers"]
                for header in headers:
                    folded = header.casefold()
                    if wanted_columns is not None and folded not in wanted_columns:
                        continue
                    now = current_filter(table_id, folded)
                    if now is None:
                        continue
                    tagged = eff_transition.get(table_id, {}).get(folded)
                    if (tagged is not None and now is tagged[0]) or (folded in eff_suppressed.get(table_id, {}) and now is eff_suppressed[table_id][folded]):
                        to_clear.setdefault(table_id, []).append(header)
                        if tagged is not None and now is tagged[0] and tagged[1] is not None and eff_suppressed.get(table_id, {}).get(folded, _NOTHING) is not tagged[1]:
                            restore.setdefault(table_id, {})[header] = tagged[1]  # ALLSELECTED still sees the filter the row replaced
            def activate_now() -> Any:
                """Put the shadows touching X back as filters that intersect with what the context holds by then."""
                activated: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]], dict[str, frozenset[int]]]] = {}
                for layer in eff_layers:
                    wanted = dropped.get(layer.table, _NOTHING)
                    if wanted is _NOTHING or (wanted is not None and not wanted & {column.casefold() for column in layer.columns}):
                        continue
                    base_context = evaluation_contexts_by_id[layer.table]
                    allowed = BlankSet(
                        (index for index, base_row in enumerate(base_context["rows"])
                         if row_key(typed_cell(base_context, column, base_row.get(column)) for column in layer.columns) in layer.tuples),
                        row_key(None for _column in layer.columns) in layer.tuples,  # the iterated rows list the unknown member
                    )
                    _ctx, by_column, _shapes, kept = activated.setdefault(layer.table, (base_context, {}, [], {}))
                    for column in layer.columns:
                        now = current_filter(layer.table, column.casefold())
                        merged = allowed if now is None else meet_rows(allowed, now)
                        by_column[column] = merged if column not in by_column else meet_rows(by_column[column], merged)
                        kept[column] = allowed if column not in kept else meet_rows(kept[column], allowed)
                for table_id, by_header in restore.items():
                    base_context = evaluation_contexts_by_id[table_id]
                    _ctx, by_column, _shapes, _kept = activated.setdefault(table_id, (base_context, {}, [], {}))
                    for header, outer in by_header.items():
                        now = current_filter(table_id, header.casefold())
                        by_column[header] = outer if now is None else outer & now
                if not activated:
                    return evaluate(inner)
                return with_column_filters(activated, lambda: evaluate(inner), "activate")

            inner = expression
            expression = ("thunk", activate_now)
            for table_id, headers in to_clear.items():
                step = expression
                references = tuple(("reference", evaluation_contexts_by_id[table_id]["name"], header) for header in headers)
                expression = ("thunk", lambda step=step, references=references: evaluate_with_filter_clear_core(
                    step, ("call", "REMOVEFILTERS", references), "REMOVEFILTERS"))
            saved_touched_only = eff_touched
            eff_touched = eff_touched | {
                (table_id, name) for table_id, columns in dropped.items()
                for name in (columns if columns is not None else {h.casefold() for h in evaluation_contexts_by_id[table_id]["headers"]})
            }
            try:
                return evaluate(expression)
            finally:
                eff_touched = saved_touched_only
        saved_eff = (eff_layers, eff_touched)
        layers, touched = eff_layers, eff_touched
        for table_id, columns in dropped.items():
            every = columns is None
            names = frozenset(h.casefold() for h in evaluation_contexts_by_id[table_id]["headers"]) if every else columns
            if function != "ALLSELECTED":  # ALLSELECTED as a filter argument is not a projection of the shadows
                layers = project_layers(layers, table_id, names)
            touched = touched | {(table_id, name) for name in names}
        eff_layers, eff_touched = layers, touched
        try:
            return evaluate_with_filter_clear_core(expression, modifier, function, *rest, **named)
        finally:
            eff_layers, eff_touched = saved_eff

    def allexcept_clear_plan(arguments: tuple[Any, ...], include_inactive: bool = False) -> dict[str, set[str] | None]:
        """table id -> casefolded columns ALLEXCEPT clears: every column of the first table and of the tables on its one side
        except the kept ones. Power BI refuses a kept column outside that expansion and a call that keeps everything."""
        table = resolve_table_context(str(arguments[0][1]))
        expansion = expanded_table_ids(table["id"], include_inactive)
        kept_columns = allexcept_kept_columns(arguments)
        if any(table_id not in expansion for table_id in kept_columns):
            raise MeasureError(
                "All arguments within an ALLEXCEPT function must be related to (or contained by) its first table."
            )
        plan: dict[str, set[str] | None] = {}
        for table_id in expansion:
            headers = {h.casefold() for h in evaluation_contexts_by_id[table_id]["headers"]}
            plan[table_id] = headers - kept_columns.get(table_id, set())
        if not any(plan.values()):
            raise MeasureError("ALLEXCEPT keeps every column of the table and the tables related to it.")
        return plan

    def reject_invalid_allexcept(nodes: Iterable[Any]) -> None:
        """Power BI compiles the whole query: an ALLEXCEPT it refuses is an error even in a branch that never runs. Judged
        against every relationship, active or not, so a USERELATIONSHIP that makes it valid is never refused."""
        seen: set[int] = set()
        pending = list(nodes)
        while pending:
            node = pending.pop()
            if isinstance(node, (tuple, list)):
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if len(node) == 3 and node[0] == "call" and node[1] == "ALLEXCEPT" and isinstance(node[2], (tuple, list)) and node[2]:
                    arguments = tuple(node[2])
                    if arguments[0][0] == "table":
                        allexcept_clear_plan(arguments, include_inactive=True)
                if len(node) == 3 and node[0] == "reference" and not node[1] and isinstance(node[2], str) and node[2].casefold() in parsed:
                    pending.append(parsed[node[2].casefold()])
                pending.extend(item for item in node if isinstance(item, (tuple, list)))

    def evaluate_with_filter_clear_core(
        expression: tuple[Any, ...],
        modifier: tuple[Any, ...],
        function: str,
        filter_arguments: tuple[tuple[Any, ...], ...] = (),
        extra_date_filters: dict[
            tuple[str, str], tuple[dict[str, Any], str, frozenset[int]]
        ] | None = None,
        table_filter_argument: tuple[Any, ...] | None = None,
    ) -> Decimal | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        nonlocal unknown_member_exclusions
        captured_table_filter = (
            table_filter_matching_indexes(table_filter_argument)
            if table_filter_argument is not None
            else None
        )
        modifier_arguments = modifier[2]
        clear_all = not modifier_arguments
        target_context: dict[str, Any] | None = None
        columns_to_clear: set[str] = set()
        # table id -> casefolded columns to clear (None = the whole table); ALL(T) / ALLEXCEPT(T, ...) reach the one-side tables too
        clear_plan: dict[str, set[str] | None] = {}
        if function == "ALLEXCEPT":
            target_context = resolve_table_context(str(modifier_arguments[0][1]))
            clear_plan = allexcept_clear_plan(modifier_arguments)
            columns_to_clear = clear_plan[target_context["id"]] or set()
        elif modifier_arguments and modifier_arguments[0][0] == "table":
            target_context = resolve_table_context(str(modifier_arguments[0][1]))
            for table_id in (expanded_table_ids(target_context["id"]) if function != "ALLSELECTED" else [target_context["id"]]):
                clear_plan[table_id] = None
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
            clear_plan[target_context["id"]] = columns_to_clear

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
            targets = [updated_by_id[table_id] for table_id in clear_plan]

        for updated in targets:
            table_columns = clear_plan.get(updated["id"], set()) if not clear_all else set()
            if function == "ALLEXCEPT" and not table_columns:
                continue
            if clear_all or (clear_plan.get(updated["id"], _NOTHING) is None):
                updated.pop("filter_rows", None)
                updated.pop("filter_table_rows", None)
                updated.pop("filter_shapes", None)
                updated.pop("filter_column_extra", None)
                updated["filter_column_rows"] = {}
                updated["filter_column_blank_allowed"] = {}
                updated["filter_context_complete"] = True
                updated_filter_roots.discard(updated["id"])
                continue

            existing_column_rows = dict(updated.get("filter_column_rows", {}))
            if _context_shapes(updated):
                clear_columns_from_shapes(updated, table_columns, existing_column_rows)
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
                column: _frozen(indexes)
                for column, indexes in existing_column_rows.items()
                if column.casefold() not in table_columns
            }
            updated["filter_column_rows"] = remaining_column_rows
            prune_cleared_shapes(updated, table_columns)
            updated["filter_column_blank_allowed"] = {
                column: allowed
                for column, allowed in updated.get(
                    "filter_column_blank_allowed", {}
                ).items()
                if column.casefold() not in table_columns
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

        if captured_table_filter is not None:
            table_id, matching_indexes = captured_table_filter
            updated = updated_by_id[table_id]
            updated["filter_rows"] = [
                row
                for row_index, row in enumerate(updated["rows"])
                if row_index in matching_indexes
            ]
            updated["filter_table_rows"] = frozenset(matching_indexes)
            updated.pop("filter_shapes", None)
            updated.pop("filter_column_extra", None)
            updated["filter_column_rows"] = {}
            updated["filter_column_blank_allowed"] = {}
            updated["filter_context_complete"] = False
            updated_filter_roots.add(table_id)
            narrow_one_side_tables(updated_by_id, updated_filter_roots, table_id, matching_indexes)
        elif function == "ALLNOBLANKROW" and target_context is not None and modifier_arguments[0][0] == "table":
            # the table without its blank row is the expanded table of the rows that exist: only the one-side rows they point at
            narrow_one_side_tables(updated_by_id, updated_filter_roots, target_context["id"], range(len(target_context["rows"])))

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
        if not clear_all and target_context is not None and function != "ALLNOBLANKROW":
            for related_id, related_columns in clear_plan.items():
                if related_id != target_context["id"] and related_columns is None:
                    updated_unknown_member_exclusions.pop(related_id, None)  # the one-side table is cleared whole too
        unknown_member_exclusions = updated_unknown_member_exclusions  # the propagation below must see the blank members this call excludes
        try:
            filtered_rows_by_id = propagate_relationship_filters(
                updated_contexts,
                relationship_definitions,
                updated_filter_roots,
            )
        except RelationshipError as exc:
            unknown_member_exclusions = previous_unknown_member_exclusions
            raise MeasureError(
                f"Could not apply {function}: {exc}"
            ) from exc
        except BaseException:
            unknown_member_exclusions = previous_unknown_member_exclusions
            raise
        context_sequence += 1
        current_context = context_sequence
        evaluation_contexts_by_id = updated_by_id
        evaluation_filter_ids = updated_filter_roots
        rows_by_table_id = filtered_rows_by_id
        try:
            if filter_arguments or extra_date_filters is not None:
                return evaluate_with_boolean_filters(
                    expression, filter_arguments, extra_date_filters
                )
            return evaluate(expression)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids
            unknown_member_exclusions = previous_unknown_member_exclusions

    def evaluate_with_table_filter(
        expression: tuple[Any, ...],
        filter_node: tuple[Any, ...],
    ) -> Decimal | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        try:
            table_id, matching_indexes = table_filter_matching_indexes(filter_node)
        except MeasureError:  # a predicate the compiled form cannot express: test every row instead
            return evaluate_with_general_filters(expression, (filter_node,))
        target_context = evaluation_contexts_by_id[table_id]

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
        updated.pop("filter_shapes", None)
        updated.pop("filter_column_extra", None)
        updated["filter_column_rows"] = {}
        updated["filter_context_complete"] = False
        updated_filter_roots = set(evaluation_filter_ids)
        updated_filter_roots.add(table_id)
        narrow_one_side_tables(updated_by_id, updated_filter_roots, table_id, matching_indexes)

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
            return evaluate(expression)
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids


    def _context_shapes(context: dict[str, Any]) -> list[dict[str, Any]]:
        """The sets of whole rows that currently filter a table (a FILTER table argument is one), if any."""
        shapes = context.get("filter_shapes")
        if shapes is not None:
            return list(shapes)
        if "filter_table_rows" in context:  # the row set an enclosing FILTER(table, ...) produced
            columns = tuple(context["headers"])
            return [{"columns": columns, "rows": frozenset(context["filter_table_rows"]), "active": columns, "dirty": False}]
        return []

    def clear_columns_from_shapes(context: dict[str, Any], cleared: set[str], column_rows: dict[str, frozenset[int]]) -> None:
        """Remove columns (lower case) from the sets of whole rows that filter a table.

        What is left of each set keeps constraining the other columns by the rows' values there; those columns'
        row sets are rewritten into column_rows. Sets that lose all their columns disappear."""
        extra = {
            column: rows for column, rows in context.get("filter_column_extra", {}).items()
            if column.casefold() not in cleared
        }
        shapes: list[dict[str, Any]] = []
        for shape in _context_shapes(context):
            remaining = tuple(column for column in shape["active"] if column.casefold() not in cleared)
            if len(remaining) == len(shape["active"]):
                shapes.append(shape)
                continue
            if not remaining:
                continue
            if shape["dirty"]:
                raise MeasureError(
                    "Clearing one column of a FILTER table that was combined with other filters on the same "
                    "columns is not supported yet."
                )
            projected = shape_projection_rows(context, shape["rows"], remaining)
            for column in remaining:
                column_rows[column] = projected & extra[column] if column in extra else projected
            shapes.append({**shape, "active": remaining})
        context["filter_shapes"] = tuple(shapes)
        context["filter_column_extra"] = extra
        context.pop("filter_table_rows", None)  # the shapes now carry the rows of that FILTER table
        context["filter_context_complete"] = True

    def prune_cleared_shapes(context: dict[str, Any], cleared: set[str]) -> None:
        """Forget the sets of whole rows whose columns were all cleared."""
        shapes = _context_shapes(context)
        if shapes or "filter_shapes" in context:
            context["filter_shapes"] = tuple(
                shape for shape in shapes if not {column.casefold() for column in shape["active"]} <= cleared
            )
        if "filter_column_extra" in context:
            context["filter_column_extra"] = {
                column: rows for column, rows in context["filter_column_extra"].items() if column.casefold() not in cleared
            }

    def with_column_filters(
        filters_by_table: dict[str, tuple[Any, ...]],
        thunk: Any,
        transition: bool | str = False,
        wiped: bool = False,
    ) -> Any:
        """Run thunk() with column filters (allowed row indexes per column) replacing those columns' filters.

        A filter on one column of a FILTER table drops only that column from the table's rows: the other columns
        keep constraining by the rows' values there (Power BI: CALCULATE(CALCULATE(n, Region="East"),
        FILTER(Facts, Quantity>2)) counts the East row that has Quantity>2, not every East row)."""
        nonlocal rows_by_table_id, context_sequence, current_context
        nonlocal evaluation_contexts_by_id, evaluation_filter_ids
        nonlocal eff_layers, eff_suppressed, eff_transition, eff_group_keys, eff_touched
        if transition and transition != "activate" and not wiped:
            # live Power BI: a row of a table iterated over a date key (SUMX(ALL(Cal[Date]), ..)) first removes the other
            # outer filters of that table, like a CALCULATE filter on the key does
            wipe_names = [
                str(entry[0]["name"]) for entry in filters_by_table.values()
                if len(entry[1]) < len(entry[0]["headers"]) and any(is_date_key(entry[0], column) for column in entry[1])
            ]
            if wipe_names:
                def wiped_body(names: list[str] = wipe_names) -> Any:
                    if not names:
                        return with_column_filters(filters_by_table, thunk, transition, True)
                    return evaluate_with_filter_clear(
                        ("thunk", lambda: wiped_body(names[1:])), ("call", "REMOVEFILTERS", (("table", names[0]),)), "REMOVEFILTERS")
                return wiped_body()
        updated_by_id = {key: dict(value) for key, value in evaluation_contexts_by_id.items()}
        updated_filter_roots = set(evaluation_filter_ids)
        saved_eff = (eff_layers, eff_suppressed, eff_transition, eff_group_keys, eff_touched)
        new_layers, new_suppressed, new_transition = eff_layers, dict(eff_suppressed), dict(eff_transition)
        new_keys, new_touched = dict(eff_group_keys), eff_touched
        for table_id, entry in filters_by_table.items():
            base_context, column_rows = entry[0], entry[1]
            touched = frozenset(column.casefold() for column in column_rows)
            if transition == "activate":  # a shadow put back as an ordinary filter (ALLSELECTED(X) as a CALCULATE argument)
                for column in (entry[3] if len(entry) > 3 else {}):
                    folded = column.casefold()
                    merged_rows = column_rows.get(column)
                    before = current_filter(table_id, folded)
                    tagged = new_transition.get(table_id, {}).get(folded)
                    if tagged is not None and before is tagged[0]:  # the intersection stays "only a transition" where it was
                        new_transition[table_id] = {**new_transition[table_id], folded: (merged_rows, tagged[1])}
                    elif folded in new_suppressed.get(table_id, {}) and before is new_suppressed[table_id][folded]:
                        new_suppressed[table_id] = {**new_suppressed[table_id], folded: merged_rows}
            elif transition == "keys":  # SUMMARIZE group keys: seen by ALLSELECTED on columns they do not belong to
                new_keys[table_id] = {**new_keys.get(table_id, {}), **{column.casefold(): rows for column, rows in column_rows.items()}}
            elif transition:  # the row's values become filters ALLSELECTED never sees
                new_transition[table_id] = {**new_transition.get(table_id, {}), **{
                    column.casefold(): (rows, current_filter(table_id, column.casefold())) for column, rows in column_rows.items()
                }}  # the filter object it set, and the outer filter it replaced (which ALLSELECTED still sees)
            else:  # an explicit filter replaces the shadow on its columns
                replaced = touched - frozenset(column.casefold() for column in (entry[3] if len(entry) > 3 else {}))
                for shape in (entry[2] if len(entry) > 2 else []):
                    replaced |= frozenset(column.casefold() for column in shape["columns"])
                new_layers = project_layers(new_layers, table_id, replaced)
                new_touched = new_touched | {(table_id, column) for column in touched}
                for column, allowed in (entry[3] if len(entry) > 3 else {}).items():
                    # KEEPFILTERS intersects with the shadow instead of replacing it: it becomes one more constraint. The real
                    # filter on the column is now (transition or replaced outer filter) AND the kept one, so ALLSELECTED
                    # must keep ignoring that part: the merged object takes over the old one's role.
                    folded = column.casefold()
                    merged_rows = column_rows.get(column)
                    before = current_filter(table_id, folded)
                    tagged = new_transition.get(table_id, {}).get(folded)
                    if tagged is not None and before is tagged[0]:
                        new_transition[table_id] = {**new_transition[table_id], folded: (merged_rows, tagged[1])}
                    elif folded in new_suppressed.get(table_id, {}) and before is new_suppressed[table_id][folded]:
                        new_suppressed[table_id] = {**new_suppressed[table_id], folded: merged_rows}
                    keep_rows = base_context["rows"]
                    new_layers = (*new_layers, _Shadow(
                        table_id, (column,),
                        lambda column=column, allowed=allowed, keep_rows=keep_rows, base_context=base_context: frozenset(
                            row_key([typed_cell(base_context, column, keep_rows[index].get(column))]) for index in allowed
                        ),
                    ))
            new_shapes = entry[2] if len(entry) > 2 else []
            kept_columns = entry[3] if len(entry) > 3 else {}
            target_context = updated_by_id.get(table_id)
            if target_context is None:
                target_context = dict(base_context)
                updated_by_id[table_id] = target_context
            updated_column_rows = dict(target_context.get("filter_column_rows", {}))
            overridden = {column.casefold() for column in column_rows if column not in kept_columns}
            extra = {
                column: rows for column, rows in target_context.get("filter_column_extra", {}).items()
                if column.casefold() not in overridden
            }
            for column, rows in kept_columns.items():  # a KEEPFILTERS filter stays on top of whatever shape there is
                extra[column] = rows if column not in extra else rows & extra[column]
            surviving: list[dict[str, Any]] = []
            for shape in _context_shapes(target_context):
                remaining = tuple(column for column in shape["active"] if column.casefold() not in overridden)
                if len(remaining) == len(shape["active"]):
                    surviving.append(shape)
                    continue
                if not remaining:
                    continue  # every column of the shape is replaced, so nothing of it is left
                if shape["dirty"]:
                    raise MeasureError(
                        "A filter on one column of a FILTER table that was combined with other filters on the same "
                        "columns is not supported yet."
                    )
                projected = shape_projection_rows(target_context, shape["rows"], remaining)
                for column in remaining:
                    updated_column_rows[column] = projected & extra[column] if column in extra else projected
                surviving.append({**shape, "active": remaining})
            updated_column_rows.update(column_rows)
            blank_flags = dict(target_context.get("filter_column_blank_allowed", {}))
            for column, rows in column_rows.items():
                blank_flags[column] = bool(getattr(rows, "blank", False))
            target_context["filter_column_blank_allowed"] = blank_flags
            surviving.extend(new_shapes)
            target_context["filter_shapes"] = tuple(surviving)
            target_context["filter_column_extra"] = extra
            target_context["filter_column_rows"] = updated_column_rows
            target_context["filter_context_complete"] = True
            target_context["filter_rows"] = [
                row for row_index, row in enumerate(target_context["rows"])
                if all(row_index in indexes for indexes in updated_column_rows.values())
            ]
            updated_filter_roots.add(table_id)
        try:
            filtered_rows_by_id = propagate_relationship_filters(
                list(updated_by_id.values()), relationship_definitions, frozenset(updated_filter_roots),
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
        evaluation_filter_ids = frozenset(updated_filter_roots) if isinstance(previous_filter_ids, frozenset) else updated_filter_roots
        rows_by_table_id = filtered_rows_by_id
        eff_layers, eff_suppressed, eff_transition, eff_group_keys, eff_touched = new_layers, new_suppressed, new_transition, new_keys, new_touched
        try:
            return thunk()
        finally:
            rows_by_table_id = previous_rows
            current_context = previous_context
            evaluation_contexts_by_id = previous_contexts
            evaluation_filter_ids = previous_filter_ids
            eff_layers, eff_suppressed, eff_transition, eff_group_keys, eff_touched = saved_eff

    def transition_filters(
        iterated_table: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]]:
        """The column filters that one row of an iterated table turns into (context transition)."""
        lineage = iterated_table.get("lineage")
        if lineage is not None:
            # a derived table: only the columns that come from a loaded table become filters
            filters: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]] = {}
            for header in iterated_table["headers"]:
                link = lineage.get(header)
                if link is None:
                    continue
                base_context, base_column = link
                base_context = contexts_by_id.get(base_context["id"], base_context)  # a derived copy of a loaded table: positions are the table's
                wanted = row.get(header)
                if not iterated_table.get("derived"):
                    wanted = typed_cell(base_context, base_column, wanted)
                allowed = frozenset(
                    index for index, base_row in enumerate(base_context["rows"])
                    if cell_key(typed_cell(base_context, base_column, base_row.get(base_column)))
                    == cell_key(wanted)
                )
                filters.setdefault(base_context["id"], (base_context, {}))[1][base_column] = BlankSet(allowed, wanted is None)
            for base_id, (base_context, base_filters) in list(filters.items()):  # every column of a loaded table: the row reaches its one side too
                if base_id in contexts_by_id and len(base_filters) == len(base_context["headers"]) and (not iterated_table.get("derived") or iterated_table.get("row_identity")):
                    reverse = {column: header for header, (ctx, column) in lineage.items() if ctx["id"] == base_id}
                    add_one_side_transition(base_id, {column: row.get(header) for column, header in reverse.items()}, filters, typed=bool(iterated_table.get("derived")))
            return filters
        table_id = iterated_table["id"]
        # each column filters to the rows that hold this row's value in it; together they select the row itself,
        # and clearing some columns (ALLEXCEPT, ALL(column)) leaves the others still filtered by value
        per_column: dict[str, list[int]] = {header: [] for header in iterated_table["headers"]}
        base_table = contexts_by_id.get(table_id)
        # a derived copy of a loaded table (ALLSELECTED(T), a subset): its positions are not the table's, so the filter
        # must be found among the loaded rows
        source_rows = base_table["rows"] if base_table is not None and iterated_table["rows"] is not base_table["rows"] else iterated_table["rows"]
        for row_index, iterate_row in enumerate(source_rows):
            for header in iterated_table["headers"]:
                left, right = iterate_row.get(header), row.get(header)
                _reject_power_query_error(left, header, row_index + 1)
                _reject_power_query_error(right, header, None)
                if cell_key(left) == cell_key(right):
                    per_column[header].append(row_index)
        transitioned = {table_id: (iterated_table, {header: BlankSet(indexes, row.get(header) is None) for header, indexes in per_column.items()})}
        if base_table is not None:
            add_one_side_transition(table_id, row, transitioned)
        return transitioned

    one_side_index_cache: dict[tuple[str, str], dict[Any, frozenset[int]]] = {}

    def one_side_value_index(one_context: dict[str, Any], column: str) -> dict[Any, frozenset[int]]:
        """key of a value in a one-side column -> the rows holding it (built once per column)."""
        cache_key = (one_context["id"], column)
        index = one_side_index_cache.get(cache_key)
        if index is None:
            grouped: dict[Any, list[int]] = {}
            for position, one_row in enumerate(one_context["rows"]):
                grouped.setdefault(cell_key(typed_cell(one_context, column, one_row.get(column))), []).append(position)
            index = {key: frozenset(positions) for key, positions in grouped.items()}
            one_side_index_cache[cache_key] = index
        return index

    def add_one_side_transition(
        table_id: str, row: dict[str, Any], transitioned: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]],
        typed: bool = False,
    ) -> None:
        """Iterating a row of a table also filters every table on its one side to that row's related rows (live Power BI: the
        row context of Fact reaches Dim and Cal, so SUMX(Fact, CALCULATE(COUNTROWS(Dim))) counts one dimension row per fact row).
        """
        many_context = contexts_by_id[table_id]
        for one_id, from_column, to_column in one_side_links(table_id):
            one_context = contexts_by_id.get(one_id)
            if one_context is None or one_id in transitioned:
                continue
            key_value = row.get(from_column) if typed else typed_cell(many_context, from_column, row.get(from_column))
            matches = one_side_value_index(one_context, to_column).get(cell_key(key_value))
            if not matches:  # an unmatched key belongs to the unknown member: the one side is filtered to that member only
                peer = any(
                    isinstance(item, dict) and item.get("is_active") and item.get("cardinality") == "one_to_one"
                    and {str(item.get("from_table_id")), str(item.get("to_table_id"))} == {table_id, one_id}
                    for item in relationship_definitions
                )
                transitioned[one_id] = (one_context, {header: BlankSet((), True, peer, not peer) for header in one_context["headers"]})
                continue
            related_row = one_context["rows"][min(matches)]
            transitioned[one_id] = (one_context, {
                header: BlankSet(
                    one_side_value_index(one_context, header).get(cell_key(typed_cell(one_context, header, related_row.get(header))), frozenset()),
                    related_row.get(header) is None,
                )
                for header in one_context["headers"]
            })
            add_one_side_transition(one_id, related_row, transitioned)  # a stored row, never typed

    def without_row_contexts(thunk: Any) -> Any:
        """CALCULATE evaluates its expression with the row contexts it transitioned removed."""
        saved = list(row_stack)
        del row_stack[:]
        try:
            return thunk()
        finally:
            row_stack[:] = saved

    def evaluate_with_context_transition(
        expression_node: tuple[Any, ...],
        iterated_table: dict[str, Any],
        row: dict[str, Any],
        keys: bool = False,
    ) -> Decimal | bool | None:
        '''Create a filter context mimicking the current row context and evaluate.'''
        return with_column_filters(transition_filters(iterated_table, row), lambda: evaluate(expression_node), "keys" if keys else True)

    def all_row_context_filters(
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]]:
        """Context transition folds every enclosing row context, outer to inner; an inner column replaces an outer one."""
        frames = list(row_stack)
        if row_context is not None and (not frames or frames[-1][1] is not row_context[1]):
            frames.append(row_context)
        merged: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]]]] = {}
        for frame in frames:
            iterated_table, row = frame[0], frame[1]
            if not iterated_table.get("headers") or (iterated_table.get("derived") and iterated_table.get("lineage") is None):
                continue  # the filter-constant placeholder and tables without loaded columns filter nothing
            for table_id, (base_context, column_rows) in transition_filters(iterated_table, row).items():
                merged.setdefault(table_id, (base_context, {}))[1].update(column_rows)
        return merged

    legacy_calculate_cache: dict[int, tuple[Any, bool]] = {}

    def uses_legacy_calculate(arguments: tuple[tuple[Any, ...], ...]) -> bool:
        """Whether the long-standing CALCULATE paths handle these filter arguments (checked once per call site)."""
        cached = legacy_calculate_cache.get(id(arguments))
        if cached is not None and cached[0] is arguments:
            return cached[1]
        try:
            _legacy_calculate_filters_valid(arguments)
            legacy = True
        except MeasureError:
            legacy = False
        legacy_calculate_cache[id(arguments)] = (arguments, legacy)
        return legacy

    def shape_member(value: Any) -> Any:
        return cell_key(ascii_fold(value) if isinstance(value, str) else value)

    def shape_projection_rows(context: dict[str, Any], source_rows: Any, columns: tuple[str, ...]) -> frozenset[int]:
        """The rows of a loaded table that agree, on these columns, with at least one of the given rows."""
        base_rows = context["rows"]

        def key(row: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(shape_member(typed_cell(context, column, row.get(column))) for column in columns)

        wanted = {key(base_rows[index]) for index in source_rows}
        return frozenset(index for index, row in enumerate(base_rows) if key(row) in wanted)

    def meet_rows(left: frozenset[int], right: frozenset[int]) -> frozenset[int]:
        """Intersection of two allowed-row sets; the blank member survives only when both keep it."""
        return BlankSet(left & right, bool(getattr(left, "blank", False)) and bool(getattr(right, "blank", False)))

    def general_table_filter_sets(node: tuple[Any, ...]) -> dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]]]]:
        """A table-valued CALCULATE filter: the loaded rows whose lineage-column values appear in the table.

        Power BI keeps such a filter as a set of whole rows over its columns (a "shape"): a later filter on one of
        those columns drops only that column from the rows' identity. Each entry therefore carries the shape too."""
        context, rows = table_argument_value(node)
        lineage = context.get("lineage")
        if lineage is None:
            if context.get("derived"):
                return {}  # a table with no loaded column filters nothing
            lineage = {header: (context, header) for header in context["headers"]}
        groups: dict[str, tuple[dict[str, Any], list[tuple[str, str]]]] = {}
        for header in context["headers"]:
            link = lineage.get(header)
            if link is not None:  # positions are the loaded table's: a table value may carry a copy with the blank member appended
                groups.setdefault(link[0]["id"], (contexts_by_id.get(link[0]["id"], link[0]), []))[1].append((header, link[1]))
        if not groups:
            return {}  # no column with lineage: nothing to filter

        def member(value: Any) -> Any:
            return cell_key(ascii_fold(value) if isinstance(value, str) else value)

        filters: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]]]] = {}
        for table_id, (base_context, pairs) in groups.items():
            wanted = set()
            for row in rows:
                values = []
                for header, base_column in pairs:
                    value = row.get(header)
                    values.append(member(value if context.get("derived") else typed_cell(base_context, base_column, value)))
                wanted.add(tuple(values))
            allowed = BlankSet(
                (index for index, base_row in enumerate(base_context["rows"])
                 if tuple(member(typed_cell(base_context, column, base_row.get(column))) for _header, column in pairs) in wanted),
                tuple(member(None) for _pair in pairs) in wanted,  # the table lists the blank member (VALUES / ALL, never FILTER(T, ..))
            )
            columns = tuple(column for _header, column in pairs)
            filters[table_id] = (
                base_context, {column: allowed for column in columns},
                [{"columns": columns, "rows": allowed, "active": columns, "dirty": False}],
            )
            if {column.casefold() for column in columns} == {header.casefold() for header in base_context["headers"]}:
                # a filter over every column of a table is a filter of the table with the tables on its one side
                for one_id, one_rows in referenced_one_side_rows(table_id, allowed).items():
                    one_context = contexts_by_id[one_id]
                    one_columns = tuple(one_context["headers"])
                    if one_rows is None:  # the unknown member stays: the table is left unfiltered (no column filters = cleared, see apply_additions)
                        filters.setdefault(one_id, (one_context, {}, []))
                        continue
                    filters.setdefault(one_id, (
                        one_context, {column: one_rows for column in one_columns},
                        [{"columns": one_columns, "rows": one_rows, "active": one_columns, "dirty": False}],
                    ))
        return filters

    _TIME_SCALAR_POSITIONS = {"DATESINPERIOD": (1, 2), "DATESBETWEEN": (1, 2), "DATEADD": (1,), "PARALLELPERIOD": (1,)}

    def preevaluate_time_scalars(node: tuple[Any, ...]) -> tuple[Any, ...]:
        """The start / bound / count of a date-set function is a scalar evaluated in the context CALCULATE is written in, before
        its sibling filters and before the row transition (live Power BI: a bare MAX(Cal[Date]) sees no pin, CALCULATE(MAX(..)) does)."""
        arguments = list(node[2])
        for position in _TIME_SCALAR_POSITIONS[node[1]]:
            if position >= len(arguments):
                continue
            argument = arguments[position]
            if argument[0] in {"number", "string", "blank", "thunk"} or (argument[0] == "unary" and argument[2][0] == "number"):
                continue
            try:
                # with the row context of the enclosing iterator: an explicit CALCULATE in the start transitions the row
                value = evaluate(argument, row_stack[-1] if row_stack else None, allow_text=True, allow_boolean=True)
            except (MeasureError, _DivisionError):
                continue  # left for the date-set code to report
            arguments[position] = ("thunk", lambda value=value: value)
        return (node[0], node[1], tuple(arguments))

    def preevaluate_set_chain(node: tuple[Any, ...]) -> tuple[Any, ...]:
        """The bounds of a DATESBETWEEN in a CALCULATE filter are read in the outer context, also when the date column itself is
        read after the transition (live Power BI, iteration 84)."""
        if not (node[0] == "call" and node[1] in dax_time_sets.SET_FUNCTIONS and node[2]):
            return node
        arguments = list(node[2])
        arguments[0] = preevaluate_set_chain(arguments[0])
        rebuilt = ("call", node[1], tuple(arguments))
        return preevaluate_time_scalars(rebuilt) if node[1] in _TIME_SCALAR_POSITIONS else rebuilt

    def preevaluate_filter_scalars(node: tuple[Any, ...]) -> tuple[Any, ...]:
        """Evaluate, once in the outer context, the right-hand side of a `column <op> scalar` Boolean filter (Power BI
        evaluates it before the filter is applied; inside the per-row test a CALCULATETABLE would transition the test's
        own row context). Functions Power BI refuses there are refused here too. Shapes whose Power BI semantics were
        not established (the scalar on the left, a CALCULATETABLE scalar below the top level) are refused, not guessed."""
        if node[0] == "comparison" and len(node) == 4 and _contains_function_call(node, "CALCULATETABLE"):
            left, right = node[2], node[3]
            if not (
                not row_stack and current_context == 0
                and any(True for _ in _direct_column_references(left)) and not _contains_function_call(left, "CALCULATETABLE")
                and not any(True for _ in _direct_column_references(right)) and _calculatetable_hoistable(right)
            ):
                raise _CalculateTableFilterRefusal("A CALCULATETABLE inside a True/False filter is supported only on the right of a comparison at the top level, with Boolean filters.")
        if node[0] == "comparison" and len(node) == 4:
            for operand in (node[2], node[3]):
                transitions = _contains_transition_call(operand) or any(
                    not item[1] and item[2].casefold() in by_name for item in _iter_reference_nodes(operand)
                )  # a measure reference is an implicit CALCULATE
                if operand[0] != "reference" and transitions and any(True for _ in _direct_column_references(operand)):
                    # a column mixed with a value that transitions rows, in one operand: Power BI treats that value as a
                    # constant, but only a whole operand is hoisted here (tools/parity/dax_battery_critic_shapes.json)
                    raise _CalculateTableFilterRefusal("A True/False filter cannot mix a column and a CALCULATE-based value in one operand in this local subset.")
            for side_index, other_index in ((3, 2), (2, 3)):
                side, other = node[side_index], node[other_index]
                if side[0] in {"number", "string", "boolean", "blank", "reference"} or not any(True for _ in _direct_column_references(other)):
                    continue
                if any(True for _ in _direct_column_references(side)):
                    continue
                if _contains_refused_call_outside_x_iterator(side):
                    raise MeasureError("CALCULATE and FILTER cannot be used inside a True/False filter expression.")
                if side_index == 2:
                    try:
                        filter_constant(side)
                    except _DivisionError:
                        pass
                    except MeasureRuntimeError as error:
                        raise _HardError(str(error)) from error  # evaluated before the filter, like the scalar on the right
                    except MeasureError:
                        pass
                    continue  # the scalar on the left keeps the older per-row path
                if _is_text_selectedvalue_against_number(side, other):
                    raise MeasureError("DAX comparison operations do not support comparing values of type Integer with values of type Text.")
                try:
                    value = filter_constant(side)
                except _DivisionError:
                    return node  # Infinity stays an error value for the paths below
                except MeasureRuntimeError as error:
                    raise _HardError(str(error)) from error  # the scalar side is evaluated before the filter; its error is thrown
                except MeasureError:
                    return node  # leave it to the paths that report the specific error
                if value is None:
                    literal: tuple[Any, ...] = ("blank",)
                elif isinstance(value, bool):
                    literal = ("boolean", value)
                elif isinstance(value, Decimal):
                    literal = ("number", value)
                elif isinstance(value, str):
                    literal = ("string", value)
                else:
                    return node
                return node[:side_index] + (literal,) + node[side_index + 1:]
            return node
        if node[0] == "call" and node[1] in dax_time_sets.SET_FUNCTIONS:
            return preevaluate_set_chain(node)
        if node[0] == "logical":
            return (node[0], node[1], preevaluate_filter_scalars(node[2]), preevaluate_filter_scalars(node[3]))
        if node[0] == "call" and node[1] in {"AND", "OR", "NOT", "KEEPFILTERS"}:
            return (node[0], node[1], tuple(preevaluate_filter_scalars(argument) for argument in node[2]))
        if node[0] == "call" and node[1] in _TIME_SCALAR_POSITIONS:
            return preevaluate_time_scalars(node)
        return node

    def _is_text_selectedvalue_against_number(side: tuple[Any, ...], other: tuple[Any, ...]) -> bool:
        """SELECTEDVALUE(text column) compared with a numeric column: Power BI refuses by static type, even when it is blank."""
        if not (side[0] == "call" and side[1] == "SELECTEDVALUE" and side[2] and side[2][0][0] == "reference" and other[0] == "reference"):
            return False
        try:
            left_context, left_column = resolve_table(side[2][0][1], side[2][0][2])
            right_context, right_column = resolve_table(other[1], other[2])
        except MeasureError:
            return False
        categories = [
            iterator_type_category(str(c.get("column_types", {}).get(col, "unknown")).casefold())
            for c, col in ((left_context, left_column), (right_context, right_column))
        ]
        return categories == ["text", "numeric"]

    def is_date_key(context: dict[str, Any], column: str) -> bool:
        """A dateTime column that keys its table: on the one side of a relationship, or the marked date column."""
        if context.get("column_types", {}).get(column) != "date":
            return False
        if column == context.get("date_column"):
            return True
        for relationship in relationship_definitions:
            if not isinstance(relationship, dict) or relationship.get("relationship_version") != 1:
                continue
            cardinality = relationship.get("cardinality")
            one_ends = []
            if cardinality in {"many_to_one", "one_to_one"}:
                one_ends.append((relationship.get("to_table_id"), relationship.get("to_column")))
            if cardinality in {"one_to_many", "one_to_one"}:
                one_ends.append((relationship.get("from_table_id"), relationship.get("from_column")))
            if (context["id"], column) in one_ends:
                return True
        return False

    def date_key_wipe_tables(arguments: tuple[tuple[Any, ...], ...]) -> list[str]:
        """Tables whose other filters a CALCULATE removes first because one of its (replacing) filter arguments sets a date key
        column: Boolean tests of it, FILTER(ALL(key), ..), TREATAS onto it and the time-intelligence functions over it
        (RE-D, 28,639 live probes). KEEPFILTERS, ALL(key), VALUES(key), FILTER(Table, ..) and non-key columns do not wipe."""
        names: list[str] = []
        already: set[str] = set()  # tables a clearing modifier of this CALCULATE already empties of filters

        def add_held_key_tables(name: str) -> None:
            # live Power BI (iteration 84, critic): a table held in a VAR is plain data once it is a filter, so it replaces the date key
            # like TREATAS onto it, whatever function made it (ALL(key) in a VAR wipes, ALL(key) written inline does not)
            held = variables.get(name)
            held = held() if held is not None else None
            if isinstance(held, _TableValue):
                add_lineage_key_tables(held[0])

        def add_lineage_key_tables(context: dict[str, Any]) -> None:
            for lineage_table, lineage_column in context.get("lineage", {}).values():
                if lineage_table["name"].casefold() not in already and lineage_table["name"] not in names and is_date_key(lineage_table, lineage_column):
                    names.append(str(lineage_table["name"]))
        for argument in arguments[1:]:
            if argument[0] == "call" and argument[1] in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW"} and argument[2] and argument[2][0][0] == "table":
                try:
                    cleared = expanded_table_ids(resolve_table_context(str(argument[2][0][1]))["id"])
                except MeasureError:
                    continue
                already.update(str(evaluation_contexts_by_id[table_id]["name"]).casefold() for table_id in cleared)
        for argument in arguments[1:]:
            node = argument
            if node[0] == "call" and node[1] == "KEEPFILTERS":
                continue
            references: list[tuple[Any, ...]] = []
            if node[0] == "call" and node[1] in dax_time_sets.SET_FUNCTIONS:
                found = _first_reference(node, variable_nodes.get)
                references = [] if found is None else [found]
            elif node[0] == "call" and node[1] in _TIME_FILTER_FUNCTIONS:
                references = [item for item in node[2][:1] if item[0] == "reference"]
            elif node[0] == "call" and node[1] == "TREATAS":
                references = [item for item in node[2][1:] if item[0] == "reference"]
            elif node[0] == "call" and node[1] == "FILTER":
                base = node[2][0]
                if base[0] == "call" and base[1] == "ALL" and len(base[2]) == 1 and base[2][0][0] == "reference":
                    references = [base[2][0]]
                elif base[0] == "table_call" and base[1] == "VALUES" and base[2][0] == "reference":
                    references = [base[2]]  # live Power BI (iteration 84): FILTER(VALUES(key), ..) replaces the key like FILTER(ALL(key), ..)
                elif base[0] == "var":
                    add_held_key_tables(base[1])
                elif base[0] == "call" and (base[1] in dax_time_sets.SET_FUNCTIONS or base[1] in _TIME_FILTER_FUNCTIONS or base[1] in _LINEAGE_WIPE_TABLES):
                    try:  # FILTER over a date set or a computed date table replaces the key like FILTER(ALL(key), ..)
                        add_lineage_key_tables(table_argument_value(base)[0])
                    except MeasureError:
                        pass
            elif node[0] == "table_call" and node[1] in {"VALUES", "DISTINCT"} and node[2][0] == "reference":
                references = [node[2]]  # live Power BI (iteration 84): VALUES(key) / DISTINCT(key) as a filter replaces the key like a Boolean test of it
            elif (
                node[0] == "call" and node[1] == "CALCULATETABLE" and node[2] and node[2][0][0] == "table_call"
                and node[2][0][1] == "VALUES" and node[2][0][2][0] == "reference"
            ):
                references = [node[2][0][2]]
            elif node[0] == "var":
                add_held_key_tables(node[1])
            elif node[0] == "call" and node[1] == "CALCULATETABLE" and node[2] and node[2][0][0] == "var":
                add_held_key_tables(node[2][0][1])
            elif node[0] == "call" and node[1] in _LINEAGE_WIPE_TABLES:
                # live Power BI (iteration 84, critic): a computed table over the date key (UNION / EXCEPT of date sets, TOPN, SELECTCOLUMNS ..)
                # replaces the key like TREATAS onto it
                try:
                    add_lineage_key_tables(table_argument_value(node)[0])
                except MeasureError:
                    pass  # the filter itself reports its error when it is evaluated
            elif node[0] != "call" or node[1] in {"NOT", "AND", "OR"}:
                references = list(_direct_column_references(node))
            for reference in references:
                try:
                    context, column = resolve_table(reference[1], reference[2])
                except MeasureError:
                    continue
                name = str(context["name"])
                if name.casefold() not in already and name not in names and is_date_key(context, column):
                    names.append(name)
        return names

    def _table_names_of(node: Any, names: set[str]) -> bool:
        """Collect the (case-folded) table names a filter and its scalars read; False when one cannot be named."""
        if not isinstance(node, tuple) or not node:
            return True
        if node[0] == "table":
            names.add(str(node[1]).casefold())
        elif node[0] == "reference":
            if not node[1]:
                return False
            names.add(str(node[1]).casefold())
        return all(_table_names_of(child, names) for child in node if isinstance(child, tuple))

    def plan_calculatetable_filter(argument: tuple[Any, ...]) -> tuple[bool, tuple[Any, ...]] | None:
        """A CALCULATETABLE in a Boolean filter that the older rule (a hoistable scalar on the right) refused: apply the hoist-or-transition rule
        Power BI showed (analytics_studio/dax_ct_filters.py), or return None to keep refusing. Only for a filter written at the top level."""
        planned = dax_ct_filters.plan(argument, _direct_column_references)
        if planned is None:
            return None
        if planned.scalars > 1 and (row_stack or current_context != 0):
            return None  # iteration 88 (fresh live probes): two such scalars in one filter, inside an iterator or under an outer CALCULATE, read differently
        if _contains_refused_call_outside_x_iterator(argument):
            raise MeasureError("CALCULATE and FILTER cannot be used inside a True/False filter expression.")
        names: set[str] = set()
        if not _table_names_of(argument, names) or len(names) != 1:
            return None  # the rule was established on one table; a second table reads relationships Power BI was not asked about
        replacements: dict[int, tuple[Any, ...]] = {}
        for scalar in planned.hoisted:
            try:
                if planned.counted:
                    # iteration 88 (live probes, also inside iterators and under an outer CALCULATE): the COUNTROWS(CALCULATETABLE(..)) is read with the
                    # filters of every column the filter replaces (its own and those its CALCULATETABLE tests) removed
                    value = evaluate(
                        ("call", "CALCULATE", (scalar, ("call", "ALL", (*planned.columns, *planned.extra_columns)))),
                        row_stack[-1] if row_stack else None, allow_text=True, allow_boolean=True,
                    )
                else:
                    value = filter_constant(scalar)
            except MeasureError:
                return None  # an error inside the scalar: left to the paths that report it
            if value is None:
                replacements[id(scalar)] = ("blank",)
            elif isinstance(value, bool):
                replacements[id(scalar)] = ("boolean", value)
            elif isinstance(value, Decimal):
                replacements[id(scalar)] = ("number", value)
            elif isinstance(value, str):
                replacements[id(scalar)] = ("string", value)
            else:
                return None

        def substitute(node: Any) -> Any:
            if not isinstance(node, tuple) or not node:
                return node
            if id(node) in replacements:
                return replacements[id(node)]
            return tuple(substitute(child) if isinstance(child, tuple) else child for child in node)

        if planned.mode == dax_ct_filters.HOIST and not planned.counted:
            return True, substitute(argument)  # the scalars are constants now: the older single-column path takes it from here
        all_columns = (*planned.columns, *planned.extra_columns)
        try:
            for reference in all_columns:
                resolve_table(reference[1], reference[2])
        except MeasureError:
            return None
        core = dax_ct_filters.core_of(argument)
        filtered = ("call", "FILTER", (("call", "ALL", tuple(all_columns)), substitute(core)))
        probe = argument
        while probe is not core:  # KEEPFILTERS(..) stays around the table filter
            filtered = ("call", "KEEPFILTERS", (filtered,))
            probe = probe[2][0]
        return False, filtered  # a table filter now: nothing left to pre-evaluate

    def preevaluate_calculate_boolean_filter(argument: tuple[Any, ...]) -> tuple[Any, ...]:
        # the rule of dax_ct_filters first: it also fixes shapes the older path answered without refusing (a CALCULATE-carrying X-iterator
        # on the left of the comparison was evaluated per row there, where Power BI evaluates it once)
        planned = plan_calculatetable_filter(argument) if dax_ct_filters.has_calculatetable(argument) else None
        if planned is not None:
            again, replaced = planned
            return preevaluate_filter_scalars(replaced) if again else replaced
        if dax_ct_filters.has_nested_transition_scalar(argument, _direct_column_references):
            # fresh live probes: an X-iterator over CALCULATE(CALCULATE(..)) beside a column was answered per row by the older path; Power BI
            # answered differently in 6 of 6 (CALCULATE(COUNTROWS(Facts), MAXX(ALL(Facts[Region]), CALCULATE(CALCULATE(..))) <= Facts[Quantity]))
            raise _CalculateTableFilterRefusal("Nested CALCULATE inside a scalar next to a column of a True/False filter is not supported in the local engine.")
        return preevaluate_filter_scalars(argument)

    def preevaluate_calculate_boolean_filters(
        arguments: tuple[tuple[Any, ...], ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> tuple[tuple[Any, ...], ...]:
        """CALCULATE evaluates every filter in the context it is written in: fix the scalar sides before any path runs."""
        pushed = row_context is not None and (not row_stack or row_stack[-1][1] is not row_context[1])
        if pushed:
            row_stack.append(row_context)  # type: ignore[arg-type]
        try:
            return (arguments[0], *(in_row_expression(lambda argument=argument: preevaluate_calculate_boolean_filter(argument)) for argument in arguments[1:]))
        finally:
            if pushed:
                row_stack.pop()

    def general_boolean_filter_sets(node: tuple[Any, ...]) -> dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]]]]:
        """A Boolean CALCULATE filter is FILTER(ALL(referenced columns), expression): test it on every row of the table."""
        if _contains_refused_call_outside_x_iterator(node):
            raise MeasureError("CALCULATE and FILTER cannot be used inside a True/False filter expression.")
        node = preevaluate_filter_scalars(node)
        if _has_membership_in_computed_table(node):
            raise MeasureError("IN inside a filter expression does not accept a table computed by SUMMARIZE, TOPN, SELECTCOLUMNS, EXCEPT or INTERSECT.")
        columns: dict[str, tuple[dict[str, Any], list[str]]] = {}
        for reference in _direct_column_references(node):
            context, actual = resolve_table(reference[1], reference[2])
            names = columns.setdefault(context["id"], (context, []))[1]
            if actual not in names:
                names.append(actual)
        if len(columns) != 1:
            raise MeasureError("A Boolean CALCULATE filter must reference columns of exactly one table.")
        table_id, (context, names) = next(iter(columns.items()))
        distinct: dict[tuple[Any, ...], dict[str, Any]] = {}
        for raw in context["rows"]:
            values = {name: typed_cell(context, name, raw.get(name)) for name in names}
            distinct.setdefault(row_key(values[name] for name in names), values)
        group_context, group_rows = derived_table(
            list(names), list(distinct.values()), {name: (context, name) for name in names},
            {name: context.get("column_types", {}).get(name, "text") for name in names},
        )
        group_context["boolean_filter"] = True  # window functions do not read this predicate row as a row context
        passing = {
            row_key(frame[1][name] for name in names)
            for frame in iterate_rows(group_context, group_rows)
            if conjuncts_pass(node, frame)
        }
        blank_passes = False
        if table_id in unknown_member_ids:  # the virtual blank member is a row of BLANKs: does the test hold for it?
            try:
                blank_passes = conjuncts_pass(node, (group_context, {name: None for name in names}, len(group_rows) + 1))
            except MeasureError:
                blank_passes = False
        allowed = BlankSet(
            (index for index, raw in enumerate(context["rows"])
             if row_key(typed_cell(context, name, raw.get(name)) for name in names) in passing),
            blank_passes,
        )
        shapes = [{"columns": tuple(names), "rows": allowed, "active": tuple(names), "dirty": False}] if len(names) > 1 else []
        return {table_id: (context, {name: allowed for name in names}, shapes)}

    def evaluate_with_general_filters(
        expression_node: tuple[Any, ...],
        filter_arguments: tuple[tuple[Any, ...], ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None = None,
    ) -> Any:
        """CALCULATE with any mix of Boolean, table-valued, KEEPFILTERS and clearing (ALL, ALLEXCEPT, REMOVEFILTERS) filters.

        The filters are evaluated in the original context, then a row context is transitioned, then the clearing
        modifiers run, then the filters replace (or, with KEEPFILTERS, intersect) the filters on their columns.
        USERELATIONSHIP / CROSSFILTER of the same CALCULATE change the relationships only for the expression: the clearing
        modifiers (and the tables they expand to) still read the enclosing context's relationships (tests/test_calculate_modifier_mix.py)."""
        if contains_allselected_date_column(expression_node) and any(
            argument[0] == "call" and argument[1] == "FILTER" and argument[2] and (
                argument[2][0][0] == "table"
                or (argument[2][0][0] == "call" and argument[2][0][1] == "ALL" and argument[2][0][2] and argument[2][0][2][0][0] == "table")
            )  # FILTER over a whole table (not over one column of it, which the locked ALLSELECTED shadow batteries measured)
            for argument in filter_arguments
        ) and any(
            argument[0] not in {"call", "var", "table", "thunk"} or (argument[0] == "call" and argument[1] == "KEEPFILTERS")
            for argument in filter_arguments
        ):
            # live Power BI (iteration 84, testing agent): CALCULATETABLE(NEXTMONTH(FIRSTDATE(ALLSELECTED(Cal[Date]))), Cal[MonthNo]=10,
            # FILTER(ALL(Cal), Cal[Year]=2024)) is 29 days, ours 30: ALLSELECTED sees the table filter but not the Boolean one beside it
            raise MeasureError("ALLSELECTED inside a CALCULATE that mixes a table-valued FILTER with a Boolean filter is not supported in the local engine.")
        if contains_allselected_date_column(expression_node) and sum(
            1 for argument in filter_arguments if argument[0] == "call" and argument[1] == "KEEPFILTERS"
        ) >= 2:
            # live Power BI (iteration 84, fix agent; fresh probe): COUNTROWS(DATESYTD(ALLSELECTED(Fact[Dt]))) under ALL(Cal) and two KEEPFILTERS on
            # Cal[Year] is 4, ours BLANK: what ALLSELECTED keeps of stacked KEEPFILTERS is not modelled
            raise MeasureError("ALLSELECTED over a date column beside several KEEPFILTERS is not supported in the local engine.")
        relationship_modifiers = tuple(
            argument for argument in filter_arguments if argument[0] == "call" and argument[1] in _RELATIONSHIP_MODIFIERS
        )
        if relationship_modifiers:
            filter_arguments = tuple(argument for argument in filter_arguments if argument not in relationship_modifiers)
            userelationships = tuple(argument for argument in relationship_modifiers if argument[1] == "USERELATIONSHIP")
            crossfilters = tuple(argument for argument in relationship_modifiers if argument[1] == "CROSSFILTER")
            original_expression = expression_node

            def with_relationships() -> Any:
                scoped = ("thunk", lambda: evaluate(original_expression))
                if crossfilters:
                    scoped = ("thunk", lambda inner=scoped: evaluate_with_crossfilters(inner, crossfilters))
                if userelationships:
                    scoped = ("thunk", lambda inner=scoped: evaluate_with_userelationships(inner, userelationships))
                return evaluate(scoped)

            expression_node = ("thunk", with_relationships)
        pushed = row_context is not None and (not row_stack or row_stack[-1][1] is not row_context[1])
        if pushed:
            row_stack.append(row_context)  # type: ignore[arg-type]
        try:
            clearing: list[tuple[Any, ...]] = []
            additions: list[tuple[bool, dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]]]]]] = []
            table_filters_present = False
            late_sets: list[tuple[bool, tuple[Any, ...]]] = []
            late_nonblank: list[tuple[bool, tuple[Any, ...]]] = []
            for argument in filter_arguments:  # every filter is evaluated in the original filter context
                keep, node = False, argument
                while node[:2] == ("call", "KEEPFILTERS") and len(node[2]) == 1:
                    keep, node = True, node[2][0]
                if keep and node[0] == "call" and node[1] == "ALL" and node[2]:
                    continue  # live Power BI (iteration 84, critic): KEEPFILTERS(ALL(x)) intersects with every value, so it keeps the filters as they are
                if node[0] == "call" and node[1] in {"ALL", "ALLNOBLANKROW", "REMOVEFILTERS", "ALLEXCEPT", "ALLSELECTED"}:
                    clearing.append(node)
                elif _is_late_time_set(node):
                    if row_context is not None and _late_chain_reads_data_expression(node):
                        raise MeasureError("A FIRSTNONBLANK inside a date set under a row context is not supported in the local engine.")
                    late_sets.append((keep, node))
                    table_filters_present = True
                elif _is_late_nonblank(node):
                    late_nonblank.append((keep, node))
                    table_filters_present = True
                elif _is_general_table_filter(node):
                    additions.append((keep, general_table_filter_sets(node)))
                    table_filters_present = True
                else:
                    additions.append((keep, general_boolean_filter_sets(node)))
            if table_filters_present and relationship_modifiers and unknown_member_ids and any(
                (ends := [resolve_table(column[1], column[2])[0]["id"] for column in modifier[2][:2]])
                and any(
                    table_id in ends and any(other != table_id and other in unknown_member_ids for other in ends) and table_id not in unknown_member_ids
                    for _keep, filters in additions for table_id in filters
                )
                for modifier in relationship_modifiers if modifier[1] == "USERELATIONSHIP"
            ):
                # live Power BI carries the filtered table's related-table columns through its original link into the
                # replaced one; with rows that match no member (a hidden unknown member) that is not modelled yet
                raise MeasureError(
                    "USERELATIONSHIP together with a table filter is not supported when rows match no member of the related table."
                )
            transition = all_row_context_filters(row_context) if row_context is not None else {}

            def apply_additions() -> Any:
                merged: dict[str, tuple[dict[str, Any], dict[str, frozenset[int]], list[dict[str, Any]], dict[str, frozenset[int]]]] = {}
                replaced_by_table: dict[str, set[str]] = {}
                for keep_pass in (False, True):  # replacing filters first, KEEPFILTERS then intersects with the result
                    for keep, filters in additions:
                        if keep != keep_pass:
                            continue
                        for table_id, (context, column_rows, shapes) in filters.items():
                            _context, target, target_shapes, kept = merged.setdefault(table_id, (context, {}, [], {}))
                            table_state = evaluation_contexts_by_id.get(table_id, context)
                            existing = table_state.get("filter_column_rows", {})
                            overlap = {column for column in column_rows if column in target}
                            replaced_here = replaced_by_table.setdefault(table_id, set())
                            for column, allowed in column_rows.items():
                                previous = target.get(column)
                                if previous is None and keep:
                                    covering = [shape for shape in _context_shapes(table_state) if column in shape["active"]]
                                    if not covering:
                                        previous = existing.get(column)
                                    for shape in covering:  # the rows of an enclosing FILTER table, as the replacing filters leave them
                                        if shape["dirty"]:
                                            raise MeasureError(
                                                "KEEPFILTERS over a column of a FILTER table that was combined with other "
                                                "filters on the same columns is not supported yet."
                                            )
                                        active_after = tuple(name for name in shape["active"] if name not in replaced_here)
                                        rows = shape_projection_rows(table_state, shape["rows"], active_after)
                                        previous = rows if previous is None else previous & rows
                                target[column] = allowed if previous is None else meet_rows(allowed, previous)
                            if keep:
                                # intersected with what is there, so nothing is replaced - unless a replacing filter
                                # on the same column ran first: it has already dropped the old filter (and the
                                # column from any FILTER table), and KEEPFILTERS only intersects with its result
                                for column, allowed in column_rows.items():
                                    if column not in replaced_here:
                                        kept[column] = allowed if column not in kept else meet_rows(allowed, kept[column])
                            else:
                                replaced_here.update(column_rows)
                            if overlap or keep:  # intersected filters no longer form one clean shape of whole rows
                                for shape in (*target_shapes, *shapes):
                                    if (keep and shape in shapes) or overlap & set(shape["columns"]):
                                        shape["dirty"] = True
                            target_shapes.extend(shapes)
                open_ids = [table_id for table_id, entry in merged.items() if not entry[1] and not entry[3]]
                for table_id in open_ids:  # a table filter that leaves a table unfiltered (unknown member) clears what filtered it
                    del merged[table_id]
                if merged:
                    def body() -> Any:
                        return with_column_filters(merged, lambda: without_row_contexts(lambda: evaluate(expression_node)))
                else:
                    def body() -> Any:
                        return without_row_contexts(lambda: evaluate(expression_node))
                for table_id in open_ids:
                    body = (lambda inner=body, name=evaluation_contexts_by_id[table_id]["name"]: evaluate_with_filter_clear(
                        ("thunk", inner), ("call", "REMOVEFILTERS", (("table", name),)), "REMOVEFILTERS"))
                if table_filters_present:
                    def counted(inner: Callable[[], Any] = body) -> Any:
                        full_table_filters[0] += 1  # ISCROSSFILTERED still sees a table filter in Power BI that keeps every row; the local engine does not
                        try:
                            return inner()
                        finally:
                            full_table_filters[0] -= 1
                    return counted()
                return body()

            def clear_then_apply(index: int) -> Any:
                if index == len(clearing):
                    return apply_additions()
                modifier = clearing[index]
                if modifier[1] == "ALLSELECTED":
                    return evaluate_with_allselected(("thunk", lambda: clear_then_apply(index + 1)), modifier)
                return evaluate_with_filter_clear(("thunk", lambda: clear_then_apply(index + 1)), modifier, modifier[1])

            for keep, node in late_nonblank:
                # FIRSTNONBLANK(column, expression): the candidates are the column's values after the transition, the expression
                # is read before it (live Power BI, iteration 84)
                candidates = (
                    with_column_filters(transition, lambda node=node: nonblank_candidates(node[1], node[2][0]), True)
                    if transition else nonblank_candidates(node[1], node[2][0])
                )
                additions.append((keep, general_table_filter_sets(("tablevalue", nonblank_table(node, candidates)))))

            def read_late_sets() -> Any:
                for keep, node in late_sets:  # a date column handed to a time function is read after the transition
                    additions.append((keep, general_table_filter_sets(node)))
                return clear_then_apply(0)

            if transition:
                return with_column_filters(transition, read_late_sets, True)
            return read_late_sets()
        finally:
            if pushed:
                row_stack.pop()

    variables: dict[str, Any] = {}
    full_table_filters = [0]  # CALCULATE table filters that keep every row of their table (see ISCROSSFILTERED)
    variable_kinds: dict[str, str] = {}  # static kind of each VAR in scope (see branch_kind)

    def evaluate_let(
        node: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
        allow_text: bool,
        allow_boolean: bool,
    ) -> Any:
        """VAR name = value ... RETURN body: each value is computed once, where the VAR is declared."""
        saved = dict(variables)
        saved_kinds = dict(variable_kinds)
        saved_nodes = dict(variable_nodes)
        failures: dict[str, MeasureError] = {}
        try:
            for name, value_node in node[1]:
                variable_nodes[name] = value_node
                variable_kinds[name] = branch_kind(value_node, row_context)
                if value_node[0] != "var" and _is_all_table_value_argument(value_node):
                    held_table = _TableValue(table_argument_value(value_node))
                    variables[name] = lambda held_table=held_table: held_table
                    continue
                try:
                    value = evaluate(value_node, row_context, allow_text=True, allow_boolean=allow_boolean)
                except (MeasureRuntimeError, _HardError) as error:
                    def failed(error: MeasureError = error) -> Any:
                        if isinstance(error, _DivisionError):
                            raise error  # Infinity stays an error value
                        raise _HardError(str(error)) from error  # a used VAR that failed is thrown
                    variables[name] = failed
                    failures[name] = error
                    continue
                variables[name] = lambda value=value: value
            # a closed VAR is evaluated up front, also inside an iterator: an error in one the RETURN still reads is thrown
            # even from a branch that would not run (a row-dependent VAR is only read where it is used)
            for name, value_node in node[1]:
                error = failures.get(name)
                if error is not None and not isinstance(error, _DivisionError) and (row_context is None or not reads_row(value_node)) and references_variable(node[2], name):
                    raise _HardError(str(error)) from error
            return evaluate(node[2], row_context, allow_text=allow_text, allow_boolean=allow_boolean)
        finally:
            variables.clear()
            variables.update(saved)
            variable_kinds.clear()
            variable_kinds.update(saved_kinds)
            variable_nodes.clear()
            variable_nodes.update(saved_nodes)

    def convert_value(value: Any, target: str) -> Any:
        if value is None:
            return None
        if target == "STRING":
            return dax_typed.to_text(value)
        if target == "BOOLEAN":
            if isinstance(value, str):
                lowered = value.strip().casefold()
                if lowered not in {"true", "false"}:
                    raise MeasureRuntimeError(f"Cannot convert value '{value}' of type Text to type True/False.")
                return lowered == "true"
            return dax_typed.to_boolean(value)
        number = dax_typed.to_number(value)
        if target == "INTEGER":
            if not number.is_finite():
                raise MeasureRuntimeError("An argument of function 'CONVERT' has the wrong data type or the result is too large or too small.")
            return number.quantize(Decimal(1), rounding=ROUND_HALF_UP)
        if target in {"DOUBLE", "CURRENCY"}:
            return Decimal(number) if target == "DOUBLE" else number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if target == "DATETIME":
            return dax_dates.DaxDateTime(number)
        raise MeasureError(f"CONVERT does not support the type {target}.")

    def column_order_key(value: Any) -> Any:
        return dax_typed.text_key(value) if isinstance(value, str) else value

    def filter_state(argument: tuple[Any, ...]) -> tuple[dict[str, Any], str | None, frozenset[int] | None]:
        """(table context, column or None for a whole table, allowed rows of that column's filter or None)."""
        if argument[0] == "table":
            context = resolve_table_context(str(argument[1]))
            return context, None, None
        context, actual = resolve_table(argument[1], argument[2])
        current = evaluation_contexts_by_id.get(context["id"], context)
        return context, actual, current.get("filter_column_rows", {}).get(actual)

    def evaluate_lookup_function(
        function: str,
        arguments: tuple[tuple[Any, ...], ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> Any:
        if function == "USERNAME" or function == "USERPRINCIPALNAME":
            return getpass.getuser()
        if function == "COMBINEVALUES":
            delimiter = dax_typed.to_text(evaluate(arguments[0], row_context, allow_text=True))
            return delimiter.join(
                dax_typed.to_text(evaluate(argument, row_context, allow_text=True)) for argument in arguments[1:]
            )
        if function == "ISEMPTY":
            return not table_argument_value(arguments[0])[1]
        if function == "CONTAINSROW":
            context, rows = in_row_expression(lambda: table_argument_value(arguments[0]))
            if len(arguments) - 1 != len(context["headers"]):
                raise MeasureRuntimeError("The number of arguments is invalid. Function CONTAINSROW must have a value for each column in the table expression.")
            wanted_values = in_row_expression(lambda: [evaluate(argument, row_context, allow_text=True) for argument in arguments[1:]])
            return any(
                all(
                    dax_typed.values_match(typed_cell(context, header, row.get(header)), wanted)
                    for header, wanted in zip(context["headers"], wanted_values)
                )
                for row in rows
            )
        if function == "CONTAINS":
            context, rows = table_argument_value(arguments[0])
            pairs = in_row_expression(lambda: [
                (arguments[i][2], evaluate(arguments[i + 1], row_context, allow_text=True))
                for i in range(1, len(arguments) - 1, 2)
            ])
            names = {header.casefold(): header for header in context["headers"]}
            for column, _ in pairs:
                if column.casefold() not in names:
                    raise MeasureError(f"Column {column!r} does not exist in the table passed to CONTAINS.")
            return any(
                all(
                    dax_typed.values_match(
                        typed_cell(context, names[column.casefold()], row.get(names[column.casefold()])), wanted
                    )
                    for column, wanted in pairs
                )
                for row in rows
            )
        if function == "LOOKUPVALUE":
            result_context, result_column = resolve_table(arguments[0][1], arguments[0][2])
            pair_arguments = arguments[1:]
            alternate = None
            if len(pair_arguments) % 2:
                alternate = in_row_expression(lambda: evaluate(pair_arguments[-1], row_context, allow_text=True))
                pair_arguments = pair_arguments[:-1]
            conditions = []
            for index in range(0, len(pair_arguments), 2):
                search_context, search_column = resolve_table(pair_arguments[index][1], pair_arguments[index][2])
                if search_context["id"] != result_context["id"]:
                    raise MeasureError("LOOKUPVALUE searches columns of the result column's table in the local engine.")
                conditions.append((search_column, in_row_expression(lambda index=index: evaluate(pair_arguments[index + 1], row_context, allow_text=True))))
            found: dict[Any, Any] = {}
            for source_row in result_context["rows"]:
                if all(
                    dax_typed.values_match(typed_cell(result_context, column, source_row.get(column)), wanted)
                    for column, wanted in conditions
                ):
                    value = typed_cell(result_context, result_column, source_row.get(result_column))
                    found.setdefault(cell_key(ascii_fold(value) if isinstance(value, str) else value), value)
            if len(found) > 1:
                raise MeasureRuntimeError("A table of multiple values was supplied where a single value was expected.")
            return next(iter(found.values())) if found else alternate
        if function in {"FIRSTNONBLANK", "LASTNONBLANK", "FIRSTNONBLANKVALUE", "LASTNONBLANKVALUE"}:
            base, column, raw, value = nonblank_pick(function, arguments)
            if function.endswith("VALUE"):
                return value
            return None if raw is None else typed_cell(base, column, raw)
        # filter-context questions
        context, column, filtered_rows = filter_state(arguments[0])
        current = evaluation_contexts_by_id.get(context["id"], context)
        axis = visual_axis_context
        on_axis = (
            axis is not None and axis.table_id == context["id"] and column is not None
            and axis.column.casefold() == column.casefold()
        )
        if function == "ISINSCOPE":
            return on_axis
        in_shape = any(column in shape["active"] for shape in _context_shapes(current)) if column is not None else bool(_context_shapes(current))
        if function == "ISFILTERED":
            if column is None:
                return bool(current.get("filter_column_rows")) or in_shape  # live Power BI: a FILTER(table, ..) argument filters every column of it
            return filtered_rows is not None or on_axis or in_shape
        if function == "HASONEFILTER":
            if in_shape and filtered_rows is None:
                raise MeasureError("HASONEFILTER over a column filtered by a FILTER table is not supported in the local engine.")
            if column is None or filtered_rows is None:
                return False
            return len({
                cell_key(ascii_fold(v) if isinstance(v, str) else v)
                for index, row in enumerate(context["rows"]) if index in filtered_rows
                for v in [row.get(column)]
            }) == 1
        if function == "ISCROSSFILTERED":
            crossfiltered = bool(current.get("filter_column_rows")) or len(rows_by_table_id[context["id"]]) < len(context["rows"])
            if not crossfiltered:
                # live Power BI (iteration 84, critic): a filter on another table that reaches this one through an active relationship counts
                # although it keeps every row (CALCULATE(ISCROSSFILTERED(F), U[K]<>"k0") is TRUE)
                reached = {
                    table_id for table_id in evaluation_filter_ids
                    if table_id != context["id"] and (
                        evaluation_contexts_by_id.get(table_id, {}).get("filter_column_rows") or "filter_table_rows" in evaluation_contexts_by_id.get(table_id, {})
                    )
                }
                pending = list(reached)
                while pending:
                    reached_id = pending.pop()
                    for relationship in relationship_definitions:
                        if not isinstance(relationship, dict) or not relationship.get("is_active"):
                            continue
                        ends = (str(relationship.get("from_table_id")), str(relationship.get("to_table_id")))
                        directions = relationship_filter_directions(relationship)
                        for source_end, target_end, direction in ((ends[0], ends[1], "from_to"), (ends[1], ends[0], "to_from")):
                            if source_end == reached_id and direction in directions and target_end not in reached:
                                reached.add(target_end)
                                pending.append(target_end)
                if context["id"] in reached:
                    return True
            if not crossfiltered and full_table_filters[0]:
                raise MeasureError("ISCROSSFILTERED under a table filter that keeps every row of its table is not supported.")
            return crossfiltered
        raise MeasureError(f"Function {function} is not supported by the local DAX engine.")

    def evaluate_rank_function(
        function: str,
        arguments: tuple[tuple[Any, ...], ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> Any:
        if function in {"EARLIER", "EARLIEST"}:
            depth = 1
            if function == "EARLIER" and len(arguments) > 1:
                depth = int(dax_typed.to_number(evaluate(arguments[1])))
            reference = arguments[0]
            if reference[0] != "reference":
                raise MeasureError(f"{function} needs a column reference.")

            def column_in(frame_context: dict[str, Any]) -> str | None:
                lineage = frame_context.get("lineage")
                header_by_key = {header.casefold(): header for header in frame_context["headers"]}
                header = header_by_key.get(reference[2].casefold())
                if reference[1] and lineage:
                    target = resolve_table_context(reference[1])
                    header = next((
                        h for h, (base, column) in lineage.items()
                        if base["id"] == target["id"] and column.casefold() == reference[2].casefold()
                    ), header)
                return header

            # iteration 88 (live Power BI, 30 probes on nested iterators): EARLIER(col, n) drops the n innermost row contexts, whatever tables they
            # iterate, and reads the column from the nearest one that is left and holds it; EARLIEST keeps the outermost row context alone
            # (an error when it does not hold the column).  The old rule counted only the row contexts that hold the column.
            stack = list(row_stack)
            if function == "EARLIEST":
                remaining = stack[:1] if len(stack) > 1 else []
            else:
                remaining = stack[:-depth] if depth >= 1 and len(stack) > depth else []
            frame = next((f for f in reversed(remaining) if column_in_row_context(f, reference[1], reference[2])), None)
            if frame is None:
                if not any(column_in(f[0]) is not None for f in row_stack):
                    raise MeasureError(f"Column {reference[2]!r} does not exist in the earlier row context.")
                raise MeasureRuntimeError("EARLIER/EARLIEST refers to an earlier row context which doesn't exist.")
            outer_context, outer_row, _index = frame
            header = column_in(outer_context)
            return outer_row.get(header) if outer_context.get("derived") else typed_cell(outer_context, header, outer_row.get(header))
        if function == "RANK.EQ":
            wanted = evaluate(arguments[0], row_context, allow_text=True)
            rank_context, rank_column = resolve_table(arguments[1][1], arguments[1][2])
            values = [
                typed_cell(rank_context, rank_column, row.get(rank_column))
                for row in rows_by_table_id[rank_context["id"]]
            ]
            ascending = len(arguments) > 2 and (
                str(arguments[2][1]).upper() == "ASC" if arguments[2][0] == "table" else dax_typed.to_number(evaluate(arguments[2])) != 0
            )
            if not any(dax_typed.compare("=", value, wanted) for value in values):
                return None  # a value that is not in the column has no rank
            return rank_of(wanted, values, ascending, False)
        # RANKX(table, expression, [value], [order], [ties])
        nonlocal eff_rank_table
        saved_rank_table = eff_rank_table
        eff_rank_table = True
        try:
            context, rows = table_argument_value(arguments[0])
        finally:
            eff_rank_table = saved_rank_table
        expression = arguments[1]
        scores = [
            in_row_expression(lambda frame=frame: evaluate(expression, frame, allow_text=True)) for frame in iterate_rows(context, rows)
        ]
        if len(arguments) > 2 and arguments[2][0] != "omitted":
            wanted = evaluate(arguments[2], row_context, allow_text=True)
        else:
            wanted = evaluate(expression, row_context, allow_text=True)
        ascending = False
        dense = False
        if len(arguments) > 3 and arguments[3][0] != "omitted":
            ascending = (
                str(arguments[3][1]).upper() == "ASC" if arguments[3][0] == "table" else dax_typed.to_number(evaluate(arguments[3])) != 0
            )
        if len(arguments) > 4:
            dense = arguments[4][0] == "table" and str(arguments[4][1]).upper() == "DENSE"
        return rank_of(wanted, scores, ascending, dense)

    def rank_of(wanted: Any, values: list[Any], ascending: bool, dense: bool) -> Any:
        better = [
            value for value in values
            if (dax_typed.compare("<", value, wanted) if ascending else dax_typed.compare(">", value, wanted))
        ]
        if dense:
            better = list({row_key([value]): value for value in better}.values())
        return Decimal(len(better) + 1)

    def evaluate_typed_function(
        function: str,
        arguments: tuple[tuple[Any, ...], ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    ) -> Any:
        if function == "ISERROR":
            try:
                value = evaluate(arguments[0], row_context, allow_text=True)
            except (MeasureRuntimeError, DecimalException, OverflowError):
                return True
            return dax_typed.is_non_finite(value)
        if function in {"ISONORAFTER", "ISAFTER"}:  # ASC / DESC after each (value, comparand) pair become Booleans
            arguments = tuple(
                ("boolean", dax_order.ORDER_KEYWORDS[str(argument[1]).upper()])
                if index % 3 == 2 and argument[0] == "table" and str(argument[1]).upper() in dax_order.ORDER_KEYWORDS
                else argument
                for index, argument in enumerate(arguments)
            )
        interval = None
        if function in {"DATEDIFF", "CONVERT"}:
            keyword = arguments[-1]
            if keyword[0] != "table":
                raise MeasureError(f"{function} needs a keyword such as {'DAY' if function == 'DATEDIFF' else 'INTEGER'} as its last argument.")
            interval = str(keyword[1]).upper()
            arguments = arguments[:-1]
        values = [evaluate(argument, row_context, allow_text=True) for argument in arguments]
        if function == "CONVERT":
            return convert_value(values[0], str(interval))
        if function in _DATE_FUNCTIONS:
            return dax_dates.date_function(function, values, interval)
        if function == "ISO.CEILING":
            return _scalar_math("CEILING", [
                None if values[0] is None else as_number(values[0]),
                # live Power BI (iteration 88): the sign of the significance is ignored, an omitted one is 1 and a BLANK one is 0
                Decimal(1) if len(values) < 2 else Decimal(0) if values[1] is None else abs(as_number(values[1])),
            ])
        if function in dax_ext.ARITY:
            return dax_ext.call(function, values)
        if function in dax_math.MATH_ARITY or function == "ROUND":
            return dax_math.math_function(function, values)
        if function == "ISNUMBER":
            return isinstance(values[0], Decimal)
        if function == "ISTEXT":
            return isinstance(values[0], str)
        if function == "ISNONTEXT":
            return not isinstance(values[0], str)
        if function == "ISLOGICAL":
            return isinstance(values[0], bool)
        if function == "FORMAT":
            return dax_format.format_value(values[0], values[1])
        return dax_typed.text_function(function, values)

    def plan_constant(node: tuple[Any, ...]) -> bool:
        """True when Power BI knows the value before scanning any row (tools/parity/dax_battery_evaluation_order.json).

        Literals and any function of them (also of a selected IF/SWITCH/COALESCE/IFERROR path), VARs holding one, the
        metadata aggregates (MAX/MIN of a column, COUNTROWS of a table, DISTINCTCOUNT, SELECTEDVALUE ...) while no filter is
        active, ISFILTERED/ISINSCOPE always, and a && / || / AND / OR that one such operand has already decided."""
        known: dict[int, bool] = {}
        values: dict[int, tuple[bool, Any]] = {}

        def value_of(operand: tuple[Any, ...]) -> tuple[bool, Any]:
            """(evaluated without error, the value) of a constant operand, computed once."""
            cached = values.get(id(operand))
            if cached is None:
                try:
                    cached = (True, evaluate(operand, None, allow_text=True, allow_boolean=True))
                except MeasureError:
                    cached = (False, None)
                values[id(operand)] = cached
            return cached

        def walk(operand: tuple[Any, ...]) -> bool:
            result = known.get(id(operand))
            if result is None:
                result = known[id(operand)] = decide(operand)
            return result

        def deciding(left: tuple[Any, ...], right: tuple[Any, ...], is_or: bool) -> bool:
            const_left, const_right = walk(left), walk(right)
            if const_left and const_right:
                return True
            for operand, is_const in ((left, const_left), (right, const_right)):
                if is_const:
                    ok, value = value_of(operand)
                    if ok and as_boolean(value) is is_or:
                        return True
            return False

        def decide(operand: tuple[Any, ...]) -> bool:
            kind = operand[0]
            if kind in {"number", "string", "boolean", "blank"}:
                return True
            if kind == "var":
                held = variable_nodes.get(operand[1])
                return held is not None and walk(held)
            if kind == "unary":
                return walk(operand[2])
            if kind == "logical":
                return deciding(operand[2], operand[3], operand[1] == "||")
            if kind in {"binary", "comparison"}:
                return walk(operand[2]) and walk(operand[3])
            if kind == "concat":
                return all(walk(part) for part in operand[1:])
            if kind == "table" and str(operand[1]).upper() in {"DAY", "MONTH", "YEAR", "QUARTER", "WEEK", "HOUR", "MINUTE", "SECOND", "ASC", "DESC", "TRUE", "FALSE"}:
                return True  # an interval or order keyword (DATEDIFF(a,b,DAY)) is a literal
            if kind != "call":
                return False
            function, arguments = operand[1], operand[2]
            if function in {"AND", "OR"} and len(arguments) == 2:
                return deciding(arguments[0], arguments[1], function == "OR")
            if function in {"ISFILTERED", "ISCROSSFILTERED"} and arguments and arguments[0][0] == "reference":
                return True
            if function == "ISINSCOPE" and arguments and arguments[0][0] == "reference":
                return not any(eff_transition.values())  # data once a context transition is in force
            if function in {"MAX", "MIN", "DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK", "HASONEVALUE", "SELECTEDVALUE"} and arguments and arguments[0][0] == "reference":
                return not evaluation_filter_ids and all(walk(argument) for argument in arguments[1:])
            if function in {"MINX", "MAXX"} and len(arguments) == 2 and arguments[0][0] == "table" and arguments[1][0] == "reference":
                return not evaluation_filter_ids
            if function == "COUNTROWS" and len(arguments) == 1:
                source = arguments[0]
                if source[0] == "call" and source[1] == "ALL":
                    return True
                if source[0] == "table" or (source[0] == "table_call" and source[1] in {"VALUES", "DISTINCT"}):
                    return not evaluation_filter_ids
                return False
            if function == "IF" and len(arguments) >= 2:  # only the selected path has to be constant
                if not walk(arguments[0]):
                    return False
                ok, condition = value_of(arguments[0])
                if not ok:
                    return False
                chosen = arguments[1] if as_boolean(condition) else (arguments[2] if len(arguments) > 2 else None)
                return chosen is None or walk(chosen)
            if function == "SWITCH" and len(arguments) >= 3:
                if not walk(arguments[0]):
                    return False
                ok, subject = value_of(arguments[0])
                if not ok:
                    return False
                rest = list(arguments[1:])
                for case, result in zip(rest[::2], rest[1::2]):
                    if not walk(case):
                        return False
                    matched, case_value = value_of(case)
                    if matched:
                        try:
                            if dax_typed.values_match(subject, case_value):
                                return walk(result)
                        except MeasureError:
                            return False
                return len(rest) % 2 == 0 or walk(rest[-1])
            if function == "COALESCE":
                for argument in arguments:
                    if not walk(argument):
                        return False
                    ok, value = value_of(argument)
                    if ok and value is not None:
                        return True
                return True
            if function == "IFERROR" and len(arguments) == 2:
                if not walk(arguments[0]):
                    return False
                ok, value = value_of(arguments[0])
                if ok and not dax_typed.is_non_finite(value):
                    return True
                return walk(arguments[1])
            if function == "ISERROR" and len(arguments) == 1:  # a constant that raises is not folded: it counts as data
                return walk(arguments[0]) and value_of(arguments[0])[0]
            if function in _NEVER_CONSTANT_CALLS:
                return False
            return all(walk(argument) for argument in arguments)

        return walk(node)

    def reads_row(node: tuple[Any, ...], shielded: bool = False, seen: frozenset[str] = frozenset()) -> bool:
        """Whether the expression reads the current row: a bare column or a measure outside an iterator body or an aggregate,
        EARLIER, a CALCULATE (it transitions the row), or a VAR that does. Closed expressions are hoisted by Power BI."""
        if not node:
            return False
        head = node[0]
        if head == "reference":
            return not shielded
        if head == "var":
            held = variable_nodes.get(node[1])
            return node[1] not in seen and held is not None and reads_row(held, False, seen | {node[1]})
        if head in {"table", "number", "string", "boolean", "blank"}:
            return False
        if head == "table_call":
            return any(reads_row(item, True, seen) for item in node[2:] if isinstance(item, tuple))
        if head == "call":
            function, arguments = node[1], node[2]
            if function in {"EARLIER", "EARLIEST", "CALCULATE", "CALCULATETABLE"}:
                return True
            if function in _ROW_SHIELDING_CALLS:
                return any(reads_row(argument, True, seen) for argument in arguments)
            if function in _ITERATOR_CALLS and arguments:
                if function == "XNPV" and len(arguments) == 4:
                    return (
                        reads_row(arguments[0], shielded, seen)
                        or reads_row(arguments[1], True, seen)
                        or reads_row(arguments[2], True, seen)
                        or reads_row(arguments[3], shielded, seen)
                    )
                return reads_row(arguments[0], shielded, seen) or any(reads_row(argument, True, seen) for argument in arguments[1:])
        return any(reads_row(item, shielded, seen) for item in node if isinstance(item, tuple))

    def references_variable(node: tuple[Any, ...], name: str) -> bool:
        """Whether the expression still reads the VAR after plan-time pruning: the untaken side of an IF with a constant
        condition and the operand a deciding constant removes from a && / || are not read; ISBLANK(x), ISNUMBER(x) ... are not
        a read of x either."""
        if not node:
            return False
        head = node[0]
        if head == "var":
            return node[1] == name
        if head == "call":
            function, arguments = node[1], node[2]
            if function in {"ISBLANK", "ISNUMBER", "ISTEXT", "ISLOGICAL", "ISNONTEXT"} and len(arguments) == 1 and arguments[0][0] == "var":
                return False
            if function == "IF" and len(arguments) >= 2 and plan_constant(arguments[0]):
                try:
                    taken = as_boolean(evaluate(arguments[0], None, allow_text=True, allow_boolean=True))
                except MeasureError:
                    taken = None
                if taken is not None:
                    chosen = arguments[1] if taken else (arguments[2] if len(arguments) > 2 else None)
                    return references_variable(arguments[0], name) or (chosen is not None and references_variable(chosen, name))
            if function in {"AND", "OR"} and len(arguments) == 2:
                return logical_reads(function == "OR", arguments[0], arguments[1], name)

            def settled(operand: tuple[Any, ...]) -> tuple[bool, Any]:
                if not plan_constant(operand):
                    return False, None
                try:
                    return True, evaluate(operand, None, allow_text=True, allow_boolean=True)
                except MeasureError:
                    return False, None

            if function == "COALESCE":  # arguments after the first non-blank constant are never read
                for argument in arguments:
                    if references_variable(argument, name):
                        return True
                    known, value = settled(argument)
                    if known and value is not None:
                        return False
                return False
            if function == "IFERROR" and len(arguments) == 2:
                known, value = settled(arguments[0])
                if known and not dax_typed.is_non_finite(value):
                    return references_variable(arguments[0], name)
            if function == "SWITCH" and len(arguments) >= 3:
                known, subject = settled(arguments[0])
                if known:
                    if references_variable(arguments[0], name):
                        return True
                    rest = list(arguments[1:])
                    for case, result in zip(rest[::2], rest[1::2]):
                        if references_variable(case, name):
                            return True
                        matched, case_value = settled(case)
                        if not matched and references_variable(result, name):
                            return True  # a case that cannot be decided leaves its result in the plan
                        if matched:
                            try:
                                if dax_typed.values_match(subject, case_value):
                                    return references_variable(result, name)
                            except MeasureError:
                                return True
                    return len(rest) % 2 == 1 and references_variable(rest[-1], name)
        if head == "logical":
            return logical_reads(node[1] == "||", node[2], node[3], name)
        return any(references_variable(item, name) for item in node if isinstance(item, tuple))

    def logical_reads(is_or: bool, left: tuple[Any, ...], right: tuple[Any, ...], name: str) -> bool:
        for operand, other in ((left, right), (right, left)):
            if plan_constant(operand):
                try:
                    if as_boolean(evaluate(operand, None, allow_text=True, allow_boolean=True)) is is_or:
                        return references_variable(operand, name)  # a deciding constant removes the other operand
                except MeasureError:
                    pass
        return references_variable(left, name) or references_variable(right, name)

    def time_filter_dates(date_filter: tuple[Any, ...]) -> tuple[dict[str, Any], str, set[date]]:
        """The days a date-set function selects in the current context: (date table, date column, days)."""
        date_filter_function = date_filter[1]
        date_filter_arguments = date_filter[2]
        date_reference = date_filter_arguments[0]
        date_table, actual_date_column = resolve_table(
            date_reference[1], date_reference[2]
        )
        if str(date_table["column_types"].get(actual_date_column, "")) not in {"date", "datetime"}:
            # live Power BI: any Date / DateTime column works, a fact table's Dt included (no marked date table is needed)
            raise MeasureError(
                f"{date_filter_function} needs a Date or DateTime column."
            )
        row_filters = all_row_context_filters(None) if row_stack else {}  # inside an iterator the row filters the date column (see date_column_source)
        visible_rows = (
            with_column_filters(row_filters, lambda: list(rows_by_table_id[date_table["id"]]), True) if row_filters else rows_by_table_id[date_table["id"]]
        )
        visible_dates = [
            parsed_date
            for row_index, row in enumerate(visible_rows, 1)
            if (parsed_date := _parse_measure_date(
                row.get(actual_date_column), actual_date_column, row_index
            )) is not None
        ]
        if date_filter_function == "DATEADD":
            interval_value = _scalar_count(evaluate(date_filter_arguments[1]))  # live Power BI rounds a fractional count half away from zero
            shifted_dates = _dateadd_dates(
                visible_dates,
                interval_value,
                str(date_filter_arguments[2][1]),
                [d for i, r in enumerate(date_table["rows"], 1) if (d := _parse_measure_date(r.get(actual_date_column), actual_date_column, i)) is not None],
            )
        elif date_filter_function == "SAMEPERIODLASTYEAR":
            shifted_dates = _sameperiodlastyear_dates(
                visible_dates,
                [d for i, r in enumerate(date_table["rows"], 1) if (d := _parse_measure_date(r.get(actual_date_column), actual_date_column, i)) is not None],
            )
        elif date_filter_function == "PREVIOUSYEAR":
            year_end = (
                _parse_year_end_date(date_filter_arguments[1][1])
                if len(date_filter_arguments) == 2
                else (12, 31)
            )
            if year_end == (2, 28):
                # open item of the live comparison: with a leap day in the selection Power BI starts the fiscal year on Feb 29
                raise MeasureError(f"{date_filter_function} with a February 28 year end is not supported in the local engine.")
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
        elif date_filter_function == "PREVIOUSDAY":
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            shifted_dates = _previousday_dates(
                visible_dates, available_dates
            )
        elif date_filter_function == "NEXTDAY":
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            shifted_dates = _nextday_dates(
                visible_dates, available_dates
            )
        elif date_filter_function == "NEXTMONTH":
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            shifted_dates = _nextmonth_dates(
                visible_dates, available_dates
            )
        elif date_filter_function == "NEXTQUARTER":
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            shifted_dates = _nextquarter_dates(
                visible_dates, available_dates
            )
        elif date_filter_function == "NEXTYEAR":
            year_end = (
                _parse_year_end_date(date_filter_arguments[1][1])
                if len(date_filter_arguments) == 2
                else (12, 31)
            )
            if year_end == (2, 28):
                # open item of the live comparison: with a leap day in the selection Power BI starts the fiscal year on Feb 29
                raise MeasureError(f"{date_filter_function} with a February 28 year end is not supported in the local engine.")
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            shifted_dates = _nextyear_dates(
                visible_dates, available_dates, year_end
            )
        elif date_filter_function == "PARALLELPERIOD":
            interval_value = _scalar_count(evaluate(date_filter_arguments[1]))
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            shifted_dates = _parallelperiod_dates(
                visible_dates, available_dates, interval_value, str(date_filter_arguments[2][1])
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
                start_date = _scalar_day(evaluate(date_filter_arguments[1]), "DATESBETWEEN")
                end_date = _scalar_day(evaluate(date_filter_arguments[2]), "DATESBETWEEN")
                start_date = min(available_dates) if start_date is None else start_date  # BLANK is an open end
                end_date = max(available_dates) if end_date is None else end_date
                if start_date <= end_date:
                    shifted_dates = {
                        value for value in available_dates
                        if start_date <= value <= end_date
                    }
        elif date_filter_function == "DATESINPERIOD":
            available_dates = [
                parsed_date
                for row_index, row in enumerate(date_table["rows"], 1)
                if (parsed_date := _parse_measure_date(
                    row.get(actual_date_column), actual_date_column, row_index
                )) is not None
            ]
            interval = str(date_filter_arguments[3][1]).upper()
            count = _scalar_count(evaluate(date_filter_arguments[2]))
            start_date = _scalar_day(evaluate(date_filter_arguments[1]), "DATESINPERIOD")
            shifted_dates = set()
            if available_dates and count:
                if start_date is None or start_date < min(available_dates):
                    start_date = min(available_dates)
                full_calendar = (max(available_dates) - min(available_dates)).days + 1 == len(set(available_dates))
                if start_date <= max(available_dates) and interval != "DAY" and not full_calendar:
                    # live Power BI (iteration 84, critic): over a column that is not a full calendar (a fact table's date) a month, quarter or
                    # year window is not the exact one of DAX (see _sparse_period_window)
                    window = _sparse_period_window(set(available_dates), start_date, count, interval)
                    if window is None:
                        raise MeasureError("DATESINPERIOD over a column that is not a full calendar is not supported when a forward window ends inside a month.")
                    shifted_dates = window
                elif start_date <= max(available_dates):
                    # live Power BI (903 of 903 probes): the last day of a month stays the last day of the target month
                    boundary = _shift_date(start_date, count, interval, keep_month_end=True)
                    if count < 0:
                        shifted_dates = {value for value in available_dates if boundary < value <= start_date}
                    else:
                        shifted_dates = {value for value in available_dates if start_date <= value < boundary}
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
        return date_table, actual_date_column, shifted_dates

    def date_number_mix(first: tuple[Any, ...], second: tuple[Any, ...]) -> bool:
        """Live Power BI turns a date mixed with a number (MAX(DATE(..), 5), IF(c, DATE(..), 5)) into a number; the local engine
        would keep the date, so a mix whose result is the date is refused (a number result is already right)."""
        def is_date(node: tuple[Any, ...]) -> bool:
            if node[0] == "call" and node[1] in {"DATE", "EDATE", "EOMONTH", "TODAY", "NOW", "DATEVALUE"}:
                return True
            if node[0] == "reference" and node[1]:
                try:
                    context, column = resolve_table(node[1], node[2])
                except MeasureError:
                    return False
                return str(context.get("column_types", {}).get(column, "")).casefold() in {"date", "datetime"}
            return is_date_aggregate(node)

        def is_number(node: tuple[Any, ...]) -> bool:
            return node[0] == "number" or (node[0] == "unary" and node[2][0] == "number")

        return (is_date(first) and is_number(second)) or (is_number(first) and is_date(second))

    def refuse_date_result(mixed: bool, value: Any) -> None:
        if mixed and dax_dates.is_date(value) and not row_stack:  # inside an iterator the key or branch value is only compared (locked answers)
            raise MeasureError("A date mixed with a number in one result is not supported in the local engine.")

    def refuse_date_beside_number(branches: Any, value: Any) -> None:
        """Live Power BI: IF / SWITCH / COALESCE with a number literal in one result branch give a number whichever branch runs, so a
        date result beside a number literal is refused (the local engine keeps the date type of the branch it ran)."""
        if dax_dates.is_date(value) and not row_stack and any(
            isinstance(branch, tuple) and (branch[0] == "number" or (branch[0] == "unary" and branch[2][0] == "number")) for branch in branches
        ):
            raise MeasureError("A date mixed with a number in one result is not supported in the local engine.")

    def is_date_aggregate(node: tuple[Any, ...]) -> bool:
        """MAX / MIN / MAXX / MINX of a Date column (possibly inside CALCULATE): empty, they give a typed BLANK date."""
        if node[0] != "call":
            return False
        function, arguments = node[1], node[2]
        reference = None
        if function in dax_time_sets.SET_FUNCTIONS:
            return True  # a date set is a table of dates; one value of it is a date, or a typed BLANK date
        if function in _NONBLANK_TABLES and arguments:
            reference = _first_reference(arguments[0])
        elif function in {"MAX", "MIN"} and len(arguments) == 1:
            reference = arguments[0]
        elif function == "SELECTEDVALUE" and arguments:
            reference = arguments[0]  # SELECTEDVALUE of a date column with no single selection is a typed BLANK date as well
        elif function in {"MAXX", "MINX"} and len(arguments) == 2:
            reference = arguments[1]
        elif function == "CALCULATE" and arguments:
            return is_date_aggregate(arguments[0])
        if reference is None or reference[0] != "reference" or not reference[1]:
            return False
        try:
            context, column = resolve_table(reference[1], reference[2])
        except MeasureError:
            return False
        return str(context.get("column_types", {}).get(column, "")).casefold() in {"date", "datetime"}

    ambiguous_pin_cache: dict[Any, frozenset[str]] = {}

    def refuse_ambiguous_row_pin(arguments: tuple[tuple[Any, ...], ...], row_context: tuple[dict[str, Any], dict[str, Any], int]) -> None:
        """A fact row pins its dimension, calendar and the fact itself at once.  When a second, longer route runs from one pinned
        table to another through a both-way link (ZS: Cal -> Fact2 -> Dim), live Power BI answers for the tables on that route in a
        way not yet modelled (SUMX(Fact, CALCULATE(COUNTROWS(Dim))): 8, ours 1), so reading those tables there is refused."""
        iterated = row_context[0]
        if iterated.get("derived") or iterated["id"] not in contexts_by_id:
            return
        pinned = tuple(sorted(all_row_context_filters(row_context)))
        if len(pinned) < 2:
            return
        key = (pinned, tuple(sorted(evaluation_filter_ids)), id(relationship_definitions))
        unsafe = ambiguous_pin_cache.get(key)
        if unsafe is None:
            found: dict[str, set[str]] = {}
            try:
                _propagate_relationship_filters(
                    list(evaluation_contexts_by_id.values()), relationship_definitions,
                    set(pinned) | set(evaluation_filter_ids), None, found,
                )
            except RelationshipError:
                found = {}
            unsafe = ambiguous_pin_cache[key] = frozenset(found.get("longer_route_tables", ()))
        if not unsafe:
            return
        read = set()
        for argument in arguments:
            ids = expression_table_ids(argument)
            if ids is None:
                read = set(unsafe)
                break
            read |= ids
        if read & unsafe:
            raise MeasureError(
                "A row of a table with two routes to the same table (a both-way link) filters that table in a way "
                "not supported in the local engine."
            )

    balance_running: set[int] = set()

    def contains_allselected_date_column(node: Any) -> bool:
        """Whether ALLSELECTED over a date column appears anywhere in this expression (the shape the date-set guards are about)."""
        if not isinstance(node, tuple) or not node:
            return False
        if node[0] == "call" and node[1] == "ALLSELECTED" and node[2] and isinstance(node[2][0], tuple) and node[2][0][0] == "reference":
            try:
                context, column = resolve_table(node[2][0][1], node[2][0][2])
            except MeasureError:
                context = None
            if context is not None and str(context.get("column_types", {}).get(column, "")).casefold() in {"date", "datetime"}:
                return True
        children = node if isinstance(node[0], tuple) else node[1:]
        return any(contains_allselected_date_column(child) for child in children if isinstance(child, tuple))

    def refuse_opening_balance_over_fact_dates(edge: tuple[Any, ...]) -> None:
        """Live Power BI (iteration 84, testing agent; 16 of 12,534 fresh probes): OPENINGBALANCEx(e, d) with a date SET d built over a date
        column that is not the key of a date table (OPENINGBALANCEMONTH(COUNTROWS(Fact), DATESYTD(Fact[Dt])) is 1, and the equivalent
        CALCULATE(e, PREVIOUSDAY(STARTOFMONTH(d))) is BLANK) answers where the local rewrite finds nothing, so a BLANK is refused here."""
        dates = edge[2][0][2][0]  # PREVIOUSDAY(STARTOFx(dates, ...))
        if dates[0] != "call":
            return
        def set_sources(node: Any) -> Iterable[tuple[Any, ...]]:
            """Columns the date set is built on: not the ones a scalar aggregate (MIN(Fact[Dt]) as a bound) only reads."""
            if not isinstance(node, tuple) or not node:
                return
            if node[0] == "reference":
                yield node
                return
            if node[0] == "call" and node[1] in _AGGREGATING_CALLS - {"VALUES", "DISTINCT", "ALL", "ALLSELECTED"}:
                return
            for child in (node if isinstance(node[0], tuple) else node[1:]):
                yield from set_sources(child)

        for reference in set_sources(dates):
            try:
                context, column = resolve_table(reference[1], reference[2])
            except MeasureError:
                continue
            if not is_date_key(context, column):
                raise MeasureError("OPENINGBALANCE over a date set built on a column that does not key a date table is not supported in the local engine.")

    def probe_untaken_branches(branches: list[tuple[Any, ...]], row_context: Any) -> None:
        """Live Power BI (iteration 84, testing agent): IF and SWITCH validate the branches they do not take, so a construct that is an
        error there (PREVIOUSQUARTER(KEEPFILTERS(..)), a column of a table other than the iterated one, a text column in TOTALYTD) is an
        error of the whole expression.  A branch is evaluated for that and its value dropped: a refusal in it is the expression's refusal,
        a data-dependent error (division, wrong data type) is not raised because Power BI does not report it from a branch it never takes."""
        for branch in branches:
            if branch is None or branch[0] in {"number", "string", "boolean", "blank"}:
                continue
            if _keepfilters_inside_time_function(branch):
                raise MeasureError("KEEPFILTERS inside a date-set function is an error in Power BI, also in a branch that is not taken.")
            if _bare_column_as_table(branch):
                raise MeasureError("A plain column given where a table belongs is an error in Power BI, also in a branch that is not taken.")
            try:
                evaluate(branch, row_context, allow_text=True, allow_boolean=True)
            except MeasureError as error:
                if _iterator_body_reads_a_table_column(branch):
                    # the body is validated before the table it iterates is built, so a data error or a refusal there may hide the real one
                    raise MeasureError(f"{error} The branch also has an iterator body that reads a column by table name, which the local engine cannot validate first.") from error
                # otherwise only the errors Power BI measured as raised from a branch that is not taken; every other refusal there is not the expression's
                if any(marker in str(error) for marker in _UNTAKEN_BRANCH_ERRORS):
                    raise
                # the whole branch stopped at a type check before reaching the part Power BI rejects: look at its calls one by one
                pending = [branch]
                while pending:
                    part = pending.pop()
                    for child in (part if isinstance(part[0], tuple) else part[1:]):
                        if isinstance(child, tuple) and child:
                            pending.append(child)
                    if part[0] == "call" and part is not branch:
                        try:
                            evaluate(part, row_context, allow_text=True, allow_boolean=True)
                        except MeasureError as part_error:
                            if any(marker in str(part_error) for marker in _UNTAKEN_BRANCH_ERRORS):
                                raise
                        except (DecimalException, OverflowError):
                            pass
            except (DecimalException, OverflowError):
                pass

    def strict_equal_value(node: tuple[Any, ...], row_context: tuple[dict[str, Any], dict[str, Any], int] | None) -> bool:
        """a == b (iteration 88, live Power BI, 361 operand pairs and 72 more probes): the operands must have the same type (number, text or
        True/False; a mismatch is an error); a BLANK equals only a BLANK of its own or of a compatible type, never 0, "" or FALSE, except that a
        True/False-typed BLANK is FALSE; text ignores case like =.  Dates, error values (Infinity, NaN) and computed fractions are refused."""
        column_types = {
            str(ctx.get("name", "")).casefold(): {str(h).casefold(): str(ctx.get("column_types", {}).get(h, "")).casefold() for h in ctx.get("headers", [])}
            for ctx in contexts_by_id.values()
        }
        resolved = []
        for operand in (node[1], node[2]):
            is_blank_literal = operand == ("blank",)
            value = evaluate(operand, row_context, allow_text=True, allow_boolean=True)
            static = None if is_blank_literal else _static_type(operand, column_types, {})
            if isinstance(value, bool):
                actual = "boolean"
            elif isinstance(value, str):
                actual = "text"
            elif isinstance(value, Decimal):
                actual = "number"
                if not value.is_finite():
                    raise MeasureError("== over Infinity or NaN is not supported in the local engine.")
                if value != value.to_integral_value() and operand[0] not in {"number", "reference"}:
                    raise MeasureError("== over a computed fraction is not exact in the local engine (Power BI compares doubles).")
            elif value is None:
                if is_blank_literal:
                    actual = "blank"
                elif static in {"number", "text", "boolean"}:
                    actual = static
                else:
                    raise MeasureError("== needs operands of a known type in the local engine.")
            else:
                raise MeasureError("== over dates is not supported in the local engine.")
            if static in {"number", "text", "boolean"} and actual not in {"blank", static}:
                raise MeasureError("== over operands whose type the local engine cannot establish is not supported.")
            if actual == "boolean" and value is None:
                value = False  # a True/False-typed BLANK is FALSE
            resolved.append((value, actual))
        (left, left_type), (right, right_type) = resolved
        known = {kind for kind in (left_type, right_type) if kind != "blank"}
        if len(known) > 1:
            raise MeasureError(
                f"DAX comparison operations do not support comparing values of type {left_type} with values of type {right_type}. "
                "Consider using the VALUE or FORMAT function to convert one of the values."
            )
        if left is None or right is None:
            return left is None and right is None
        if isinstance(left, str):
            if not (left.isascii() and right.isascii()):
                raise MeasureError("== over text with non-ASCII characters is not supported in the local engine (Power BI also folds width and accents).")
            return bool(dax_typed.compare("=", left, right))
        return left == right

    def evaluate(
        node: tuple[Any, ...],
        row_context: tuple[dict[str, Any], dict[str, Any], int] | None = None,
        *,
        allow_text: bool = False,
        allow_boolean: bool = False,
    ) -> Decimal | bool | str | None:
        nonlocal rows_by_table_id, context_sequence, current_context
        kind = node[0]
        if kind == "number":
            return node[1]
        if kind == "string":
            return node[1]
        if kind in {"blank", "blank_comment"}:
            return None
        if kind == "boolean":
            return node[1]
        if kind == "var":
            held = variables[node[1]]()
            if isinstance(held, _TableValue):
                if variable_nodes.get(node[1], (None,))[0] == "call" and variable_nodes[node[1]][1] in (
                    dax_time_sets.SET_FUNCTIONS | _NONBLANK_TABLES
                ):
                    return single_value_of((held[0], held[1]))  # a date set holds one date (or none) where one value is wanted
                raise MeasureError("A table variable cannot be used where a single value is expected.")
            return held
        if kind == "let":
            return evaluate_let(node, row_context, allow_text, allow_boolean)
        if kind == "concat":
            left = evaluate(node[1], row_context, allow_text=True)
            right = evaluate(node[2], row_context, allow_text=True)
            if left is None and right is None:
                return None
            return dax_typed.to_text(left) + dax_typed.to_text(right)
        if kind == "table":
            raise MeasureError(
                "A table name is only supported as the first argument to COUNTROWS, SUMX, AVERAGEX, MAXX, MINX, COUNTX, or COUNTAX."
            )
        if kind == "reference":
            _, table, name = node
            measure_key = name.casefold()
            if measure_key in by_name:
                if not table and measure_key in shadowed_measure_keys():
                    # live Power BI (iteration 84, critic): [Name] binds to the column when the measure's own table has a column of that name
                    # (SUMX(Fact,[Qty]) is the column sum, a bare [Qty] is an error), so the local engine does not guess
                    raise MeasureError(f"[{escape_bracket_name(name)}] is both a measure and a column of its table; the reference is ambiguous in the local engine.")
                if row_context is not None:
                    return with_column_filters(all_row_context_filters(row_context), lambda: evaluate(node), True)
                return resolve(measure_key)
            if row_context is not None:
                row_context = enclosing_row_context_for(row_context, table, name)
                iterated_table, row, row_index = row_context
                value_table = resolve_table_context(table) if table else iterated_table
                lineage = iterated_table.get("lineage")
                if table and value_table["id"] != iterated_table["id"] and lineage:
                    mapped = next((
                        header for header, (base, column) in lineage.items()
                        if base["id"] == value_table["id"] and column.casefold() == name.casefold()
                    ), None)
                    if mapped is not None and iterated_table.get("selected_columns") and mapped.casefold() != name.casefold():
                        mapped = None  # live Power BI (iteration 88): T[col] is not found among the renamed columns of SELECTCOLUMNS (an error)
                    if mapped is not None:
                        name, value_table = mapped, iterated_table
                if value_table["id"] != iterated_table["id"]:
                    raise MeasureError(
                        "Iterator expressions can reference columns from their iterated table only."
                    )
                header_by_key = {
                    header.casefold(): header for header in iterated_table["headers"]
                }
                actual = header_by_key.get(name.casefold())
                if actual is None:
                    raise MeasureError(
                        f"Column {name!r} does not exist in table {iterated_table['name']!r}."
                    )
                source_value = row.get(actual)
                if iterated_table.get("derived"):
                    return source_value  # a derived table already holds DAX values
                _reject_power_query_error(source_value, actual, row_index)
                raw_value = "" if source_value is None else cell_to_text(source_value)
                if not raw_value or (not allow_text and not raw_value.strip()):
                    return None
                column_types = iterated_table.get("column_types", {})
                has_declared_type = actual in column_types
                column_type = str(column_types.get(actual, "text")).casefold()
                if column_type in {"date", "datetime"}:
                    return _cell_date_value(source_value, actual, row_index)
                if column_type == "boolean" or (allow_boolean and not has_declared_type):
                    lowered = raw_value.strip().casefold()
                    if lowered in {"true", "false"}:
                        return lowered == "true"
                    raise MeasureError(
                        f"Column {actual!r} contains a value that is not True or False at row {row_index}."
                    )
                if allow_text and str(
                    iterated_table.get("column_types", {}).get(actual, "text")
                ).casefold() not in {
                    "whole_number", "decimal_number", "decimal", "fixed_decimal", "currency",
                    "number", "numeric", "int64", "double",
                }:
                    return raw_value
                try:
                    number = Decimal(raw_value.replace(",", "").strip())
                except (DecimalException, ValueError) as exc:
                    raise MeasureError(
                        f"Column {actual!r} contains a non-numeric value at row {row_index}; convert it to a number first."
                    ) from exc
                if not number.is_finite():
                    raise MeasureError(f"Column {actual!r} contains a non-finite number.")
                return number
            raise MeasureError(f"{name!r} is a column reference; use an aggregation such as SUM([{escape_bracket_name(name)}]).")
        if kind == "unary":
            operand = evaluate(node[2], row_context, allow_boolean=allow_boolean and node[1] == "+")
            if operand is None:
                return None
            if node[1] == "+" and isinstance(operand, bool):
                return operand  # unary plus leaves a True/False value alone (-TRUE() is a number)
            value = as_number(operand)
            return value if node[1] == "+" else dax_typed.QUIET.minus(value) if value else Decimal(0)
        if kind == "binary":
            left = evaluate(node[2], row_context)
            right = evaluate(node[3], row_context)
            if node[1] == "^":
                return _power(
                    None if left is None else as_number(left), None if right is None else as_number(right)
                )
            if node[1] in {"+", "-"} and (left is None) != (right is None):
                # live Power BI: MAX / MIN of an empty date column is a typed BLANK date, which counts as day zero in + and -
                if left is None and is_date_aggregate(node[2]):
                    left = dax_dates.DaxDateTime(Decimal(0))
                elif right is None and node[1] == "+" and is_date_aggregate(node[3]):
                    right = dax_dates.DaxDateTime(Decimal(0))
            result = _binary_value(
                node[1],
                None if left is None else as_number(left),
                None if right is None else as_number(right),
            )
            if node[1] in {"+", "-"} and result is not None and (
                dax_dates.is_date(left) or dax_dates.is_date(right)
            ):
                if node[1] == "-" and not dax_dates.is_date(left) and (node[2][0] in {"number", "blank"} or (node[2][0] == "unary" and node[2][2][0] == "number") or (node[2][0] == "call" and node[2][1] == "INT")):
                    return result  # live Power BI: a number literal minus a date is a plain number (other lefts may be dates the evaluator lost the type of)
                return dax_dates.DaxDateTime(dax_dates.tick_round(result))
            return result
        if kind == "logical":
            return _eager_logical(
                node[1] == "&&",
                [
                    (lambda operand=operand: as_boolean(_consume_infinity(lambda: evaluate(
                        operand, row_context, allow_text=allow_text, allow_boolean=allow_boolean,
                    ))))
                    for operand in (node[2], node[3])
                ],
                [node[2], node[3]],
                plan_constant,
            )
        if kind == "tablecapture":
            node[2].append(table_argument_value(node[1]))
            return Decimal(0)
        if kind == "thunk":
            return node[1]()
        if kind == "in":
            context, rows = in_row_expression(lambda: table_argument_value(node[2]))
            probe = node[1]
            wanted_values = in_row_expression(lambda: [evaluate(member, row_context, allow_text=True) for member in (probe[1] if probe[0] == "tuple" else (probe,))])
            if len(wanted_values) != len(context["headers"]):
                raise MeasureRuntimeError("The number of values on the left of IN must match the number of columns of the table.")
            return any(
                all(
                    dax_typed.values_match(typed_cell(context, header, row.get(header)), wanted)
                    for header, wanted in zip(context["headers"], wanted_values)
                )
                for row in rows
            )
        if kind == "strict_equal":
            return strict_equal_value(node, row_context)
        if kind == "comparison":
            compare_text = False
            compare_boolean = False
            if allow_text or allow_boolean or row_context is not None:
                try:
                    comparison_category = iterator_comparison_operand_category(
                        node, row_context
                    )
                except MeasureError:
                    if allow_text:
                        raise
                    comparison_category = ""
                compare_text = comparison_category == "text"
                compare_boolean = comparison_category == "boolean"
            left = evaluate(
                node[2], row_context, allow_text=compare_text,
                allow_boolean=compare_boolean,
            )
            right = evaluate(
                node[3], row_context, allow_text=compare_text,
                allow_boolean=compare_boolean,
            )
            if len(node) > 4:  # x IN {...}: blank only equals blank, text ignores case, mixed types are an error
                return dax_typed.values_match(left, right)
            return dax_typed.compare(node[1], left, right)
        if node[0] == "tableconstructor":
            # a constructor of one plain value is that value (Power BI: {1} is 1); any other table is not a scalar
            if len(node[1]) == 1 and node[1][0][0] not in {"tuple", "tableconstructor"}:
                return evaluate(node[1][0], row_context, allow_text=allow_text, allow_boolean=allow_boolean)
            raise MeasureError("A table constructor with more than one value cannot be used as a single value.")
        _, function, arguments = node
        if function == "RELATED":
            if row_context is None and row_stack and row_stack[-1][0].get("derived") and not row_stack[-1][0]["headers"]:
                # a scalar hoisted out of a CALCULATE filter (see filter_constant) reads the row of the enclosing iterator
                row_context = next((frame for frame in reversed(row_stack[:-1]) if frame[0]["headers"]), None)
            return related_value(arguments[0], row_context)
        if function in {"SUMX", "AVERAGEX", "MAXX", "MINX"} or function in dax_math.STAT_ITERATORS:
            try:
                context, iteration_rows = table_argument_value(arguments[0])
            except MeasureRuntimeError as error:
                if any(reference[1] for reference in _direct_column_references(arguments[1])):
                    # live Power BI: the body is validated before the table is built (MAXX(CALENDAR(later, earlier), Fact[Ship]) reports the
                    # column of the other table, not the calendar), so what the data error would hide is not known here
                    raise MeasureError(f"{error} The iterator body also reads a column by table name, which the local engine cannot validate first.") from error
                raise
            refuse_one_to_one_values_iteration(arguments[0])
            if iteration_rows and function in {"SUMX", "AVERAGEX", "MAXX", "MINX"} and _coalesce_with_failing_argument(arguments[1]):
                raise MeasureError("A COALESCE whose earlier argument can fail is evaluated in an order the local engine does not reproduce.")
            if iteration_rows and function in {"SUMX", "AVERAGEX", "MAXX", "MINX"} and _statistic_with_arithmetic(arguments[1]):
                raise MeasureError("A statistical function beside arithmetic in an iterator body is not exact in the local engine.")
            # live Power BI (iteration 87): SUMX / AVERAGEX / MAXX / MINX over a body whose IF / SWITCH / IFERROR / COALESCE branches differ in
            # type (a Variant) read only the numbers and dates it returns; text and True/False rows count for nothing (never the number a text
            # happens to spell).  Numbers beside dates, without text or True/False, are one number type: its dates are plain numbers.
            body_kind = iterator_body_kind(arguments[1], (context, iteration_rows[0] if iteration_rows else {}, 1)) if function in {"SUMX", "AVERAGEX", "MAXX", "MINX"} else None
            if body_kind is None and function in {"SUMX", "AVERAGEX"} and (
                (arguments[1][0] == "reference" and context.get("derived")) or (arguments[1][0] == "call" and arguments[1][1] in {"MAXX", "MINX", "CONCATENATEX", "FORMAT", "CALCULATE"})
            ):
                try:
                    column_category = iterator_expression_category(arguments[1], (context, iteration_rows[0] if iteration_rows else {}, 1))
                except MeasureError:
                    column_category = ""
                body_kind = {"text": "text", "boolean": "bool"}.get(column_category)
            if body_kind in {"text", "bool"} and function in {"SUMX", "AVERAGEX"}:
                raise MeasureError(f"The function {function} cannot work with values of type {'String' if body_kind == 'text' else 'Boolean'}.")
            if body_kind == "variant_dates" and function != "AVERAGEX":
                raise MeasureError(f"{function} over a Variant that holds a number type with dates inside is not supported in the local engine.")
            variant_body, number_dates = body_kind in {"variant", "variant_dates"}, body_kind == "numdate"
            if not variant_body:
                refuse_variant_aggregation(function, context, arguments[1])
            mixed_branches = bool(iteration_rows) and function not in {"MAXX", "MINX"} and body_kind is None and is_variant_column_expression(arguments[1], (context, iteration_rows[0], 1), ())
            if not iteration_rows:
                refuse_foreign_columns_of_empty_set(context, arguments[1])
            if function in {"MAXX", "MINX"} and body_kind in {"variant", "variant_dates", "numdate"}:
                result_category = "numeric"
            elif function in {"MAXX", "MINX"}:
                validation_row = iteration_rows[0] if iteration_rows else {}
                result_category = iterator_expression_category(
                    arguments[1], (context, validation_row, 1)
                )
                if result_category not in {"numeric", "blank", "date/time", "text"}:
                    raise MeasureError(
                        f"Iterator {function} expression needs a numeric result."
                    )
            text_extreme = function in {"MAXX", "MINX"} and result_category == "text"
            values: list[Decimal] = []
            for frame in iterate_rows(context, iteration_rows, "install"):
                result = in_row_expression(lambda frame=frame: evaluate(arguments[1], frame, allow_text=text_extreme or variant_body))
                if variant_body and isinstance(result, (bool, str)):
                    continue
                if variant_body and isinstance(result, Decimal) and not result.is_finite():
                    raise MeasureError(f"{function} over a Variant that returns Infinity or NaN is not supported in the local engine.")
                if number_dates and isinstance(result, dax_dates.DaxDateTime):
                    result = Decimal(result)
                if isinstance(result, bool) and function not in {"MAXX", "MINX"}:
                    raise MeasureError(f"The function {function} cannot work with values of type Boolean.")
                if isinstance(result, str) and arguments[1][0] == "reference" and function not in {"MAXX", "MINX"}:
                    raise MeasureError(f"The function {function} cannot work with values of type String.")  # a text column, even of digits
                if isinstance(result, str) and mixed_branches:
                    raise MeasureError(f"{function} over text from an expression whose branches have different types is not supported in the local engine.")
                if result is not None:
                    values.append(result if text_extreme and isinstance(result, str) else as_number(result))
                elif function in {"MEDIANX", "PERCENTILEX.INC", "PERCENTILEX.EXC"}:
                    values.append(Decimal(0))  # these three count a blank result as zero
            if function in {"SUMX", "AVERAGEX"} and _multiplies_by_constant_zero(arguments[1]) and any(isinstance(value, Decimal) and value.is_nan() for value in values):
                raise MeasureError(f"{function} over a NaN beside a product with a constant zero is not supported in the local engine (Power BI may fold it to 0).")
            if function in dax_math.STAT_ITERATORS:
                if any(isinstance(value, dax_dates.DaxDateTime) for value in values):
                    # live Power BI (iteration 84, critic): "MEDIANX does not support expressions of type string/Boolean/date"
                    raise MeasureError(f"{function} does not support expressions of type date.")
                percentile = (
                    dax_typed.to_number(evaluate(arguments[2], row_context)) if function.startswith("PERCENTILEX") else None
                )
                return dax_math.statistic(function, [value for value in values if value.is_finite()], percentile)
            if text_extreme:  # the largest or smallest text, compared without regard to case
                if not values:  # Power BI's BLANK here is a text BLANK (comparing it with a number is an error); BLANK has no type here
                    raise MeasureError(f"{function} of text found no value, and a text BLANK is not modelled by the local DAX engine.")
                winner = (max if function == "MAXX" else min)(values, key=dax_typed.text_key)
                if any(value != winner and dax_typed.text_key(value) == dax_typed.text_key(winner) for value in values):
                    # live Power BI (iteration 87): of two texts that differ only in case, MAXX / MINX return one that the local engine cannot predict
                    raise MeasureError(f"{function} found texts that differ only in case at the extreme: which one Power BI returns is not modelled by the local engine.")
                return winner
            if function in {"MAXX", "MINX"}:
                ordered = [value for value in values if not value.is_nan()]
                if not ordered:
                    return None  # NaN results are ignored; only NaN gives blank
                extreme = max(ordered) if function == "MAXX" else min(ordered)
                if variant_body and any(value == extreme and isinstance(value, dax_dates.DaxDateTime) != isinstance(extreme, dax_dates.DaxDateTime) for value in ordered):
                    raise MeasureError(f"{function} over a Variant found a date and a number of the same value at the extreme: which one Power BI returns is not modelled.")
                if extreme.is_infinite() and (extreme > 0) == (function == "MINX"):
                    return None  # live Power BI (iteration 87): MINX of nothing but +Infinity and MAXX of nothing but -Infinity are BLANK
                return extreme
            if not values:
                return None
            total = Decimal(0)
            for value in values:
                total = dax_typed.QUIET.add(total, value)
            result = total if function == "SUMX" else dax_typed.QUIET.divide(total, Decimal(len(values)))
            date_sum = any(isinstance(value, dax_dates.DaxDateTime) for value in values) if variant_body else (
                not number_dates and not has_number_branch(arguments[1]) and all(isinstance(value, dax_dates.DaxDateTime) for value in values))
            if (
                function == "SUMX" and not variant_body and not number_dates and not has_number_branch(arguments[1])
                and any(isinstance(value, dax_dates.DaxDateTime) for value in values) and not date_sum
            ):
                # live Power BI (iteration 87): [date] + 1 over rows that are BLANK for the date still sums to a date; the type is that of the
                # expression, which the local values (a plain 1 for the BLANK rows) no longer show
                raise MeasureError("SUMX over a mix of dates and plain numbers is not typed by the local engine.")
            if function == "SUMX" and date_sum and result.is_finite():
                return dax_dates.DaxDateTime(min(result, _MAX_DATE_SERIAL))  # live Power BI: a sum of dates saturates at 12/31/9999 23:59:59  # live Power BI: SUMX over dates is a date, AVERAGEX over dates is a plain number
            return result
        if function in {"COUNTX", "COUNTAX"}:
            context, iteration_rows = table_argument_value(arguments[0])
            validation_row = iteration_rows[0] if iteration_rows else {}
            if iteration_rows and _coalesce_with_failing_argument(arguments[1]):
                raise MeasureError("A COALESCE whose earlier argument can fail is evaluated in an order the local engine does not reproduce.")
            if iteration_rows and _statistic_with_arithmetic(arguments[1]):
                raise MeasureError("A statistical function beside arithmetic in an iterator body is not exact in the local engine.")
            # live Power BI (iteration 87): over a body whose IF / SWITCH / IFERROR / COALESCE branches differ in type (a Variant) COUNTX counts
            # only its numbers and dates, COUNTAX every row that is not BLANK
            count_kind = iterator_body_kind(arguments[1], (context, validation_row, 1))
            variant_body = count_kind in {"variant", "variant_dates"}
            constant_variant = function == "COUNTX" and variant_body and (_conditional_is_constant(arguments[1]) or _has_false_only_if(arguments[1]))
            if function == "COUNTX" and not variant_body:
                refuse_variant_aggregation(function, context, arguments[1])
            if not iteration_rows:
                refuse_foreign_columns_of_empty_set(context, arguments[1])
            if not variant_body and count_kind != "numdate":
                iterator_expression_category(
                    arguments[1], (context, validation_row, 1)
                )
            count = 0
            saw_nan = False
            for frame in iterate_rows(context, iteration_rows, "install"):
                result = in_row_expression(lambda frame=frame: evaluate(
                    arguments[1], frame, allow_text=True
                ))
                if result is None:
                    continue
                if function == "COUNTX" and variant_body and isinstance(result, bool) and constant_variant:
                    # live Power BI: COUNTX(Facts, IF(TRUE(), TRUE(), 7)) is 6, yet 3 when the condition depends on the row: not modelled
                    raise MeasureError("COUNTX over a Variant that returns a True/False under a condition that does not depend on the row is not supported in the local engine.")
                if function == "COUNTX" and variant_body and isinstance(result, (bool, str)):
                    continue
                if variant_body and isinstance(result, Decimal) and not result.is_finite():
                    raise MeasureError(f"{function} over a Variant that returns Infinity or NaN is not supported in the local engine.")
                if function == "COUNTX" and isinstance(result, bool):
                    raise MeasureError("The function COUNTX cannot work with values of type Boolean.")
                if isinstance(result, Decimal) and result.is_nan():
                    saw_nan = True  # live Power BI (iteration 86): 0/0 is not counted by COUNTX or COUNTAX (Infinity is), yet it is not blank
                    continue
                if isinstance(result, (Decimal, bool, str)):
                    count += 1
            if saw_nan and _multiplies_by_constant_zero(arguments[1]):
                raise MeasureError(f"{function} over a NaN beside a product with a constant zero is not supported in the local engine (Power BI may fold it to 0).")
            return Decimal(count) if count or saw_nan else None
        if function == "CALCULATE":
            if (
                len(arguments) > 1 and arguments[0][0] == "call" and arguments[0][1] == "CALCULATE"
                and any(item[0] == "call" and item[1] == "KEEPFILTERS" for item in arguments[1:])
                and any(contains_allselected_date_column(item) for item in arguments[0][2][1:])
            ):
                # live Power BI (iteration 84, fix agent; fresh probe): CALCULATE(CLOSINGBALANCEYEAR(e, ALLSELECTED(Fact[Dt])), KEEPFILTERS(Cal[Year]=2023))
                # is BLANK, ours 50: the inner ALLSELECTED sees the outer KEEPFILTERS filter, which the shadow bookkeeping does not carry over
                raise MeasureError("ALLSELECTED in the filters of a CALCULATE nested under KEEPFILTERS is not supported in the local engine.")
            if contains_allselected_date_column(arguments[0]) and sum(
                1 for item in arguments[1:] if item[0] == "call" and item[1] == "KEEPFILTERS"
            ) >= 2:
                raise MeasureError("ALLSELECTED over a date column beside several KEEPFILTERS is not supported in the local engine.")
            opening_edge = next((
                item for item in arguments[1:]
                if item[0] == "call" and item[1] == "PREVIOUSDAY" and len(item[2]) == 1 and item[2][0][0] == "call"
                and item[2][0][1] in {"STARTOFMONTH", "STARTOFQUARTER", "STARTOFYEAR"} and item[2][0][2]
            ), None)  # the shape OPENINGBALANCEx(e, d) is rewritten to (an explicit PREVIOUSDAY(STARTOFx(d)) filter has it too)
            if opening_edge is not None and id(node) not in balance_running:
                balance_running.add(id(node))
                try:
                    result = evaluate(node, row_context, allow_text=allow_text, allow_boolean=allow_boolean)
                finally:
                    balance_running.discard(id(node))
                if result is None:
                    refuse_opening_balance_over_fact_dates(opening_edge)
                return result
            if len(arguments) > 1:
                arguments = preevaluate_calculate_boolean_filters(arguments, row_context)
                wipes = date_key_wipe_tables(arguments)
                if wipes and any(a[0] == "call" and a[1] in _TIME_FILTER_FUNCTIONS for a in arguments[1:]) and not any(
                    _new_route_time_set(a) for a in arguments[1:]
                ):
                    # the date sets are computed in this context, then evaluate_with_date_values clears the table when it applies them: only
                    # for the key column the set itself reads (a set over a fact date column leaves the calendar to the other filters)
                    handled: set[str] = set()
                    for item in arguments[1:]:
                        if item[0] == "call" and item[1] in _TIME_FILTER_FUNCTIONS and item[2] and item[2][0][0] == "reference":
                            try:
                                item_table, item_column = resolve_table(item[2][0][1], item[2][0][2])
                            except MeasureError:
                                continue
                            if is_date_key(item_table, item_column):
                                handled.add(str(item_table["name"]))
                    wipes = [name for name in wipes if name not in handled]
                if wipes:  # live Power BI: replacing a date key column first removes the other filters of its table
                    arguments = (*arguments, *(("call", "REMOVEFILTERS", (("table", name),)) for name in wipes))
                node = (node[0], function, arguments)
            if row_context is not None:
                refuse_ambiguous_row_pin(arguments, row_context)
                if len(arguments) > 1 and _general_calculate_filters_valid(tuple(arguments[1:])):
                    return evaluate_with_general_filters(arguments[0], tuple(arguments[1:]), row_context)
                if len(arguments) > 2 and any(a[0] == "call" and a[1] in _RELATIONSHIP_MODIFIERS for a in arguments[1:]) and _general_calculate_filters_valid(
                    tuple(a for a in arguments[1:] if not (a[0] == "call" and a[1] in _RELATIONSHIP_MODIFIERS))
                ):
                    # live Power BI: the filter arguments are evaluated BEFORE the row transition, whatever USERELATIONSHIP / CROSSFILTER
                    # they sit beside (FILTER(Cal, ..) is the whole calendar, not the day the fact row pins)
                    return evaluate_with_general_filters(arguments[0], tuple(arguments[1:]), row_context)
                return with_column_filters(all_row_context_filters(row_context), lambda: without_row_contexts(lambda: evaluate(node)), True)
            if len(arguments) == 1:
                return evaluate(arguments[0])
            if not uses_legacy_calculate(arguments):
                if selected_iteration_depth and not _general_calculate_filters_valid(tuple(arguments[1:])):
                    # a modifier mix inside an iteration over SELECTCOLUMNS: Power BI does not find T[col] among the renamed
                    # columns (live: error) while the local engine reads it through the lineage, so the mix stays refused here
                    raise MeasureError("CALCULATE filters must be column comparisons joined with AND, OR, or NOT.")
                return evaluate_with_general_filters(arguments[0], tuple(arguments[1:]))
            try:
                userelationship_modifiers = tuple(
                    argument
                    for argument in arguments[1:]
                    if argument[0] == "call"
                    and argument[1] == "USERELATIONSHIP"
                )
                crossfilter_modifiers = tuple(
                    argument
                    for argument in arguments[1:]
                    if argument[0] == "call" and argument[1] == "CROSSFILTER"
                )
                if userelationship_modifiers and crossfilter_modifiers:
                    raise MeasureError(
                        "USERELATIONSHIP and CROSSFILTER cannot be combined in one CALCULATE call in this local subset."
                    )
                has_time_filter_arguments = any(
                    argument[0] == "call"
                    and argument[1] in _TIME_FILTER_FUNCTIONS
                    for argument in arguments[1:]
                )
                if userelationship_modifiers and not has_time_filter_arguments:
                    relationship_filter_arguments = tuple(
                        argument
                        for argument in arguments[1:]
                        if not (
                            argument[0] == "call"
                            and argument[1] == "USERELATIONSHIP"
                        )
                    )
                    return evaluate_with_userelationships(
                        arguments[0], userelationship_modifiers,
                        relationship_filter_arguments,
                    )
                if crossfilter_modifiers and not has_time_filter_arguments:
                    crossfilter_filter_arguments = tuple(
                        argument
                        for argument in arguments[1:]
                        if not (
                            argument[0] == "call"
                            and argument[1] == "CROSSFILTER"
                        )
                    )
                    return evaluate_with_crossfilters(
                        arguments[0], crossfilter_modifiers,
                        crossfilter_filter_arguments,
                    )
                mixed_allselected = [
                    (index, argument)
                    for index, argument in enumerate(arguments[1:], start=1)
                    if argument[0] == "call" and argument[1] == "ALLSELECTED"
                ]
                if len(arguments) > 2 and len(mixed_allselected) == 1:
                    modifier_index, modifier = mixed_allselected[0]
                    filter_arguments = (
                        *arguments[1:modifier_index],
                        *arguments[modifier_index + 1:],
                    )
                    if any(
                        argument[0] == "call" and argument[1] in _TIME_FILTER_FUNCTIONS
                        for argument in filter_arguments
                    ):
                        validate_allselected_modifier(modifier)
                    else:
                        return evaluate_with_allselected(
                            arguments[0], modifier, filter_arguments
                        )
                mixed_clear_modifiers = [
                    (index, argument)
                    for index, argument in enumerate(arguments[1:], start=1)
                    if argument[0] == "call"
                    and argument[1] in {
                        "REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLCROSSFILTERED",
                    }
                ]
                if len(arguments) > 2 and len(mixed_clear_modifiers) == 1:
                    modifier_index, modifier = mixed_clear_modifiers[0]
                    has_time_filters = any(
                        argument[0] == "call" and argument[1] in _TIME_FILTER_FUNCTIONS
                        for argument in arguments[1:]
                    )
                    if not has_time_filters:
                        filter_arguments = (
                            *arguments[1:modifier_index],
                            *arguments[modifier_index + 1:],
                        )
                        table_filter_arguments = tuple(
                            argument
                            for argument in filter_arguments
                            if argument[0] == "call" and argument[1] == "FILTER"
                        )
                        if table_filter_arguments:
                            filter_arguments = tuple(
                                argument
                                for argument in filter_arguments
                                if not (
                                    argument[0] == "call"
                                    and argument[1] == "FILTER"
                                )
                            )
                        return evaluate_with_filter_clear(
                            arguments[0], modifier, modifier[1],
                            filter_arguments=filter_arguments,
                            table_filter_argument=(
                                table_filter_arguments[0]
                                if table_filter_arguments
                                else None
                            ),
                        )
                if (
                    len(arguments) == 2
                    and arguments[1][0] == "call"
                    and arguments[1][1]
                    in {"REMOVEFILTERS", "ALL", "ALLNOBLANKROW", "ALLEXCEPT", "ALLCROSSFILTERED"}
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
                mixed_filter_clear = (
                    mixed_clear_modifiers[0]
                    if len(arguments) > 2 and len(mixed_clear_modifiers) == 1
                    else None
                )
                boolean_filters = tuple(
                    arg for index, arg in enumerate(arguments[1:], start=1)
                    if not (
                        arg[0] == "call" and arg[1] in _TIME_FILTER_FUNCTIONS
                    ) and not (
                        mixed_filter_clear is not None
                        and index == mixed_filter_clear[0]
                    ) and not (
                        len(arguments) > 2
                        and len(mixed_allselected) == 1
                        and index == mixed_allselected[0][0]
                    ) and not (
                        arg[0] == "call"
                        and arg[1] in {"USERELATIONSHIP", "CROSSFILTER"}
                    )
                )
                if not time_filters:
                    return evaluate_with_boolean_filters(
                        arguments[0], boolean_filters
                    )

                extra_date_filters = {}
                for date_filter in time_filters:
                    date_table, actual_date_column, shifted_dates = time_filter_dates(date_filter)
                    period_indexes = frozenset(
                        row_index
                        for row_index, row in enumerate(date_table["rows"])
                        if (parsed_date := _parse_measure_date(
                            row.get(actual_date_column), actual_date_column, row_index + 1
                        )) is not None and parsed_date in shifted_dates
                    )
                    key = (date_table["id"], actual_date_column.casefold())
                    if key in extra_date_filters:
                        period_indexes = period_indexes & extra_date_filters[key][2]  # two date sets on one column intersect
                    extra_date_filters[key] = (date_table, actual_date_column, period_indexes)

                if mixed_filter_clear is not None:
                    return evaluate_with_filter_clear(
                        arguments[0], mixed_filter_clear[1], mixed_filter_clear[1][1],
                        filter_arguments=boolean_filters,
                        extra_date_filters=extra_date_filters,
                    )
                if userelationship_modifiers:
                    return evaluate_with_userelationships(
                        arguments[0], userelationship_modifiers,
                        boolean_filters, extra_date_filters,
                    )
                if crossfilter_modifiers:
                    return evaluate_with_crossfilters(
                        arguments[0], crossfilter_modifiers,
                        boolean_filters, extra_date_filters,
                    )
                return evaluate_with_boolean_filters(
                    arguments[0], boolean_filters, extra_date_filters
                )
            except MeasureRuntimeError:
                raise
            except MeasureError as legacy_error:
                # a shape the older CALCULATE paths refuse: Power BI accepts it, so evaluate it with the general path
                if _time_filters_beside_general_filters(tuple(arguments)) and "per-column filter context" not in str(legacy_error):
                    # the date sets become table filters (evaluated in the outer context like every filter); a date key replaced
                    # by a date set first removes the other outer filters of its table
                    wipe_arguments = tuple(("call", "REMOVEFILTERS", (("table", name),)) for name in date_key_wipe_tables(arguments))
                    return evaluate_with_general_filters(arguments[0], (*arguments[1:], *wipe_arguments))
                if not _general_calculate_filters_valid(tuple(arguments[1:]), True):
                    raise
                if "per-column filter context" in str(legacy_error):
                    # A saved filter without per-column information cannot say which columns it covers, so a
                    # filter that replaces one of its columns would silently give other numbers.
                    raise
                try:
                    return evaluate_with_general_filters(arguments[0], tuple(arguments[1:]))
                except MeasureError:
                    raise legacy_error from None
        if function in dax_time_sets.SET_FUNCTIONS:
            return single_value_of(date_set_table(node))
        if function == "DATEADD":
            raise MeasureError(
                "DATEADD returns a date table; use it as a DATEADD filter in CALCULATE."
            )
        if function == "SAMEPERIODLASTYEAR":
            raise MeasureError(
                "SAMEPERIODLASTYEAR returns a date table; use it as a filter in CALCULATE."
            )
        for tbl_func in {
            "PREVIOUSYEAR", "PREVIOUSQUARTER", "PREVIOUSMONTH", "PREVIOUSDAY",
            "NEXTYEAR", "NEXTQUARTER", "NEXTMONTH", "NEXTDAY",
            "PARALLELPERIOD"
        }:
            if function == tbl_func:
                raise MeasureError(
                    f"{tbl_func} returns a date table; use it as a filter in CALCULATE."
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
                raise MeasureError(f"{function} inside measure iterators is not supported.")
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
                # live Power BI: an empty date set evaluates the expression in the empty-date context (BLANK for SUM, 1 for 1)
                return evaluate_with_date_values(arguments[0], date_table, actual_date_column, set())
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
        if function in {"IF", "IF.EAGER"}:
            mixed_branches = len(arguments) > 2 and date_number_mix(arguments[1], arguments[2])
            chosen = arguments[1] if as_boolean(_consume_infinity(lambda: evaluate(
                arguments[0], row_context, allow_text=allow_text,
                allow_boolean=allow_boolean,
            ))) else (arguments[2] if len(arguments) > 2 else None)  # IF without a false value returns blank
            try:
                value = None if chosen is None else evaluate(
                    chosen, row_context, allow_text=allow_text, allow_boolean=allow_boolean,
                )
            except _DivisionError:
                raise
            except MeasureRuntimeError as error:
                if function == "IF.EAGER":
                    raise _HardError(str(error)) from error  # live Power BI (iteration 92): an error out of IF.EAGER is thrown, IFERROR cannot catch it
                raise
            untaken = [branch for branch in arguments[1:3] if branch is not chosen]
            if function == "IF.EAGER" and row_context is not None:
                for branch in untaken:  # live Power BI (iteration 92): inside a row expression both branches are evaluated and an error in either is thrown
                    try:
                        evaluate(branch, row_context, allow_text=True, allow_boolean=True)
                    except _DivisionError:
                        pass
                    except MeasureRuntimeError as error:
                        raise _HardError(str(error)) from error
            probe_untaken_branches(untaken, row_context)
            refuse_date_result(mixed_branches, value)
            refuse_date_beside_number(arguments[1:3], value)
            if value is None and bool_join([branch_kind(branch, row_context) for branch in arguments[1:]]):
                return False  # a Boolean result has no blank: Power BI answers FALSE
            return value
        if function == "ERROR":
            raise MeasureRuntimeError(arguments[0][1])
        if function == "CUSTOMDATA":
            return None
        if function == "NAMEOF":
            arg = arguments[0]
            if arg[0] == "reference":
                context, col = resolve_table(arg[1], arg[2])
                return f"'{context['name']}'[{col}]"
            if arg[0] == "table":
                context = resolve_table_context(arg[1])
                return f"'{context['name']}'"
            raise MeasureError("Only measure or fully-qualified column or table or calendar references are allowed in NAMEOF function.")
        if function == "TABLEOF":
            raise MeasureError("The expression refers to multiple columns. Multiple columns cannot be converted to a scalar value.")
        if function == "EVALUATEANDLOG":
            for extra in arguments[1:]:  # live Power BI (iteration 92): the label and the row limit are never evaluated, but a bare column or table there is a compile-time error
                if extra[0] == "omitted":
                    continue
                try:
                    evaluate(extra, row_context, allow_text=True, allow_boolean=True)
                except MeasureError as error:
                    if "is a column reference" in str(error) or "table name" in str(error).casefold():
                        raise
            try:
                return evaluate(arguments[0], row_context, allow_text=allow_text, allow_boolean=allow_boolean)
            except MeasureRuntimeError as error:
                raise _HardError(str(error)) from error
        if function == "ALLCROSSFILTERED":
            raise MeasureError("ALLCROSSFILTERED function cannot be used as a table expression. It can appear only as a filter in CALCULATE.")
        if function == "ISBLANK":
            try:
                return _consume_infinity(
                    lambda: evaluate(arguments[0], row_context, allow_text=True, allow_boolean=allow_boolean)
                ) is None
            except MeasureRuntimeError as error:
                # ponytail: Power BI answers FALSE when the error is the argument function's own (SQRT/LN/LOG domain, UNICHAR, REPT,
                # EDATE ... "wrong data type") or a conversion of literals, but not when the argument is COALESCE/IFERROR/SWITCH/
                # CALCULATE, nor a text conversion of data. Measured by probe (dax_battery_evaluation_order), not understood.
                argument = arguments[0]
                own_error = "needs a number" in str(error) or "wrong data type" in str(error)
                swallowed = own_error or (not any(True for _ in _iter_reference_nodes(argument)) and plan_constant(argument))
                if isinstance(error, _DivisionError) or not swallowed or (
                    argument[0] == "call" and argument[1] in {"COALESCE", "IFERROR", "SWITCH", "CALCULATE", "ASIN", "ACOS", "DIVIDE"}
                ):
                    raise
                return False
        if function == "IFERROR":
            try:
                value = evaluate(arguments[0], row_context, allow_text=allow_text, allow_boolean=allow_boolean)
                failed = dax_typed.is_non_finite(value)  # Infinity and NaN count as errors here
            except (MeasureRuntimeError, DecimalException, OverflowError):
                value, failed = None, True
            if failed:
                value = evaluate(arguments[1], row_context, allow_text=allow_text, allow_boolean=allow_boolean)
            else:
                probe_untaken_branches([arguments[1]], row_context)  # live Power BI (iteration 91): a compile-time error in the unused argument is raised too
            refuse_date_beside_number(arguments[:2], value)
            if value is None and bool_join([branch_kind(arguments[0], row_context), branch_kind(arguments[1], row_context)]):
                return False
            return value
        if function in _TYPED_ARITY:
            return evaluate_typed_function(function, arguments, row_context)
        if function in _LOOKUP_ARITY and function not in {"GENERATESERIES", "ROW"}:
            return evaluate_lookup_function(function, arguments, row_context)
        if function in _TABLE_FUNCTION_ARITY or function in {"GENERATESERIES", "ROW"}:
            raise MeasureError(
                f"{function} returns a table; use it inside COUNTROWS, SUMX, CONCATENATEX or another table argument."
            )
        if function in _WINDOW_SCALARS:
            return window_scalar(function, arguments)
        if function in _RANK_ARITY:
            return evaluate_rank_function(function, arguments, row_context)
        if function == "SWITCH":
            subject = _consume_infinity(lambda: evaluate(arguments[0], row_context, allow_text=True, allow_boolean=allow_boolean))
            remaining = list(arguments[1:])
            fallback = remaining.pop() if len(remaining) % 2 else None
            matched_level = len(remaining) // 2 - 1  # a miss falls through to the last nested IF's else
            untaken = list(remaining[1::2]) + ([] if fallback is None else [fallback])
            for level, (candidate, result) in enumerate(zip(remaining[::2], remaining[1::2])):
                candidate_value = _consume_infinity(lambda: evaluate(candidate, row_context, allow_text=True, allow_boolean=allow_boolean))
                if candidate_value is None and subject is not None and _numeric_by_construction(candidate):
                    # live Power BI: a BLANK number is still a number, and SWITCH reports a number compared with a True/False or text subject
                    raise MeasureError("A SWITCH value that is BLANK cannot be type-checked against the subject in the local engine.")
                if dax_typed.values_match(subject, candidate_value):
                    value = evaluate(result, row_context, allow_text=allow_text, allow_boolean=allow_boolean)
                    matched_level = level
                    # the candidates after the match and every other result and the fallback are branches Power BI still validates
                    untaken = list(remaining[2 * level + 2:]) + [
                        branch for position, branch in enumerate(remaining[1::2]) if position != level
                    ] + ([] if fallback is None else [fallback])
                    for later in remaining[2 * level + 2::2]:  # live Power BI: the values of the later candidates must be comparable with the subject
                        if later[0] in {"number", "string", "boolean", "blank"}:
                            later_value = later[1] if later[0] != "blank" else None
                        else:
                            try:
                                later_value = evaluate(later, row_context, allow_text=True, allow_boolean=True)
                            except MeasureError:
                                continue
                            if later_value is None and _numeric_by_construction(later) and subject is not None:
                                raise MeasureError("A later SWITCH value that is BLANK cannot be type-checked against the subject in the local engine.")
                        if subject is not None and later_value is not None and (
                            isinstance(subject, bool) != isinstance(later_value, bool) or isinstance(subject, str) != isinstance(later_value, str)
                        ):
                            raise MeasureError("SWITCH cannot compare values of different types.")
                    break
            else:
                value = None if fallback is None else evaluate(fallback, row_context, allow_text=allow_text, allow_boolean=allow_boolean)
                untaken = list(remaining[1::2])
            probe_untaken_branches(untaken, row_context)
            if value is None:
                # SWITCH is nested IFs: each one turns a blank into FALSE when its own branches are Boolean
                rest = None if fallback is None else branch_kind(fallback, row_context)
                level_bool = []
                for result_branch in reversed(remaining[1::2]):
                    kinds = [branch_kind(result_branch, row_context)] + ([] if rest is None else [rest])
                    level_bool.append(bool_join(kinds))
                    rest = join_kind(kinds)
                level_bool.reverse()
                if level_bool[matched_level]:
                    return False
            refuse_date_beside_number([*remaining[1::2], *([] if fallback is None else [fallback])], value)
            return value
        if function in {"AND", "OR"}:
            return _eager_logical(
                function == "AND",
                [
                    (lambda operand=operand: as_boolean(_consume_infinity(lambda: evaluate(
                        operand, row_context, allow_text=allow_text, allow_boolean=allow_boolean,
                    ))))
                    for operand in arguments[:2]
                ],
                list(arguments[:2]),
                plan_constant,
            )
        if function == "NOT":
            return not as_boolean(_consume_infinity(lambda: evaluate(
                    arguments[0], row_context, allow_text=allow_text,
                    allow_boolean=allow_boolean,
                ))
            )
        if function == "COUNTROWS":
            if not arguments:
                visible_rows = rows_by_table_id.get(current_home_table_id, [])
                return Decimal(len(visible_rows)) if visible_rows else None
            direct_allexcept = arguments[0][0] == "call" and arguments[0][1] == "ALLEXCEPT"
            if direct_allexcept:
                counting_rows.append(True)
            lazy_columns = arguments[0][0] == "call" and arguments[0][1] in {"ADDCOLUMNS", "SELECTCOLUMNS"}
            if lazy_columns:
                lazy_column_calls.append(arguments[0])
            direct_var_table = arguments[0][0] == "var"
            if direct_var_table:
                direct_counting_table_vars.append(arguments[0][1])
            try:
                _context, table_rows = table_argument_value(arguments[0])
            finally:
                if direct_allexcept:
                    counting_rows.pop()
                if lazy_columns:
                    lazy_column_calls.pop()
                if direct_var_table:
                    direct_counting_table_vars.pop()
            return Decimal(len(table_rows)) if table_rows else None
        if function == "COALESCE":
            # Power BI stops at the first non-blank plan-time constant. From the first data-dependent argument on it also
            # evaluates the arguments after it that do not read the current row (so their errors surface); one that reads the
            # row stays lazy. An error leaving a COALESCE cannot be caught by IFERROR or ISERROR, whichever argument it is.
            result, found, eager = None, False, False
            reached: list[tuple[Any, ...]] = []
            for argument in arguments:
                if found and not eager:
                    break
                reached.append(argument)
                if not eager and not plan_constant(argument):
                    eager = True
                elif eager and found and row_context is not None and reads_row(argument) and argument is arguments[-1]:
                    continue  # a last argument that reads the row is only evaluated when it is reached (live Power BI, iteration 87: an earlier one is always evaluated)
                elif eager and found and plan_constant(argument):
                    try:
                        settled = evaluate(argument, row_context, allow_text=True, allow_boolean=True)
                    except MeasureRuntimeError as error:
                        raise _HardError(str(error)) from error  # a constant that fails is planned, so it fails the whole measure
                    if settled is not None:
                        break  # a non-blank constant ends the chain: what follows it is never planned
                try:
                    value = evaluate(
                        argument, row_context, allow_text=allow_text,
                        allow_boolean=allow_boolean,
                    )
                except MeasureRuntimeError as error:
                    if isinstance(error, _DivisionError) or (row_context is not None and reads_row(argument) and argument is arguments[-1]):
                        raise  # an error from the last, lazily evaluated, row-dependent argument is an ordinary one (live Power BI, iteration 87: one in an earlier argument is not)
                    raise _HardError(str(error)) from error
                if not found and value is not None:
                    result, found = value, True
            probe_untaken_branches([argument for argument in arguments if not any(argument is seen for seen in reached)], row_context)  # live Power BI (iteration 91): compile-time errors in arguments after the answer are raised too
            refuse_date_beside_number(arguments, result)
            return result
        if function == "DIVIDE":
            numerator_value = evaluate(arguments[0], row_context)
            denominator_value = evaluate(arguments[1], row_context)
            if numerator_value is None:
                return None
            numerator = (
                Decimal(int(numerator_value))
                if isinstance(numerator_value, bool)
                else as_number(numerator_value)
            )
            denominator = (
                Decimal(int(denominator_value))
                if isinstance(denominator_value, bool)
                else as_number(denominator_value)
            )
            if denominator == 0:
                if len(arguments) == 3:
                    alternate = evaluate(arguments[2], row_context, allow_text=True, allow_boolean=True)
                    if alternate is None or isinstance(alternate, (str, bool)):
                        return alternate
                    return as_number(alternate)
                return None
            if len(arguments) == 3 and arguments[2][0] in {"string", "boolean"}:
                raise MeasureError(
                    "DIVIDE with text or Boolean alternate result and non-zero denominator is not supported in the local engine."
                )
            return numerator / denominator
        if function == "ABS":
            value = evaluate(arguments[0], row_context)
            return None if value is None else abs(as_number(value))
        if function in _SCALAR_MATH_ARITY:
            return _scalar_math(function, [
                None if value is None else as_number(value)
                for value in (evaluate(argument, row_context) for argument in arguments)
            ])
        if function == "ROUND":
            value = as_number(evaluate(arguments[0], row_context))
            precision = as_number(evaluate(arguments[1], row_context))
            if not value.is_finite() or not precision.is_finite():
                raise MeasureRuntimeError("An argument of function 'ROUND' has the wrong data type or the result is too large or too small.")
            if precision != precision.to_integral_value() or abs(precision) > 28:
                raise MeasureError("ROUND digits must be a whole number from -28 to 28.")
            quantum = Decimal(1).scaleb(-int(precision))
            return value.quantize(quantum, rounding=ROUND_HALF_UP)
        if function == "XNPV":
            try:
                rate_raw = evaluate(arguments[3], row_context, allow_text=True, allow_boolean=True)
            except MeasureError as error:
                if "is a column reference" in str(error):
                    raise MeasureError("The Rate argument to the XNPV function needs a single value; a bare column cannot give one.") from error
                raise
            if rate_raw is None:
                rate = 0.0
            elif isinstance(rate_raw, bool):
                rate = 1.0 if rate_raw else 0.0
            elif isinstance(rate_raw, str):
                try:
                    rate = float(dax_typed.text_to_number(rate_raw))
                except Exception as exc:
                    raise MeasureError(f"Cannot convert value '{rate_raw}' of type Text to type Number.") from exc
            elif isinstance(rate_raw, (int, float, Decimal)) and not isinstance(rate_raw, dax_dates.DaxDateTime):
                rate = float(rate_raw)
            else:
                raise MeasureError("The Rate argument to the XNPV function must be a number.")
            if rate <= -1.0 or math.isnan(rate) or math.isinf(rate):
                raise MeasureError("The Rate argument to the XNPV function must be greater than -1.")

            read_nodes = [arguments[1], arguments[2]]
            topn_walk_nodes[id(arguments[0])] = read_nodes
            try:
                context, iteration_rows = table_argument_value(arguments[0])
            finally:
                topn_walk_nodes.pop(id(arguments[0]), None)

            probe_frame = (context, iteration_rows[0] if iteration_rows else {}, 1)
            try:
                values_kind = iterator_body_kind(arguments[1], probe_frame)
            except MeasureError:
                values_kind = None
            if values_kind in {"text", "bool", "date"}:
                # live Power BI (iteration 91): the type of the Values expression is checked when the query is compiled, not per row
                raise MeasureError("XNPV does not support expressions of type string/Boolean/date for the Values argument.")
            currency_values = _calls_function(arguments[1], "CURRENCY")
            for reference in _iter_reference_nodes(arguments[1]):
                try:
                    currency_values = currency_values or str(iterator_reference_type(reference, probe_frame)).casefold() in {"currency", "fixed_decimal"}
                except MeasureError:
                    pass  # a column outside the iterated table is validated further down
            if currency_values:
                raise MeasureError("XNPV over Currency values returns a Currency result, which the local engine does not model.")

            if not iteration_rows:
                refuse_foreign_columns_of_empty_iteration(context, arguments[1], arguments[2])
                return None

            row_data: list[tuple[float | None, int]] = []
            all_dates: list[int] = []
            for frame in iterate_rows(context, iteration_rows, "install"):
                val = in_row_expression(lambda frame=frame: evaluate(arguments[1], frame, allow_text=True, allow_boolean=True))
                if val is None:
                    v = None
                elif isinstance(val, (str, bool, dax_dates.DaxDateTime)):
                    raise MeasureError("XNPV does not support expressions of type string/Boolean/date for the Values argument.")
                elif isinstance(val, (int, float, Decimal)):
                    v = float(val)
                    if math.isnan(v) or math.isinf(v):
                        raise MeasureError("An argument of function 'XNPV' has the wrong data type or the result is too large or too small.")
                else:
                    raise MeasureError("XNPV does not support expressions of type string/Boolean/date for the Values argument.")

                d_val = in_row_expression(lambda frame=frame: evaluate(arguments[2], frame, allow_text=True, allow_boolean=True))
                if d_val is None:
                    raise MeasureError("One or more values for the Dates argument passed to XNPV is blank.")
                elif isinstance(d_val, str):
                    raise MeasureError(f"Cannot convert value '{d_val}' of type Text to type Date.")
                elif isinstance(d_val, bool):
                    day = 1 if d_val else 0
                elif isinstance(d_val, (int, float, Decimal)):
                    d_float = float(d_val)
                    if math.isnan(d_float) or math.isinf(d_float):
                        raise MeasureError("An argument of function 'XNPV' has the wrong data type or the result is too large or too small.")
                    day = math.floor(d_float)
                    if day > _XNPV_LAST_DAY:
                        raise MeasureError("XNPV dates after 9999-12-31 are not supported in the local engine.")
                else:
                    raise MeasureError("An argument of function 'XNPV' has the wrong data type or has an invalid value.")

                all_dates.append(day)
                row_data.append((v, day))

            non_blank_values = [v for v, _ in row_data if v is not None]
            if not non_blank_values:
                return None

            earliest_date = min(all_dates)
            total = 0.0
            for v, day in row_data:
                if v is None:
                    continue
                days_diff = day - earliest_date
                if rate == 0.0 or days_diff == 0:
                    total += v
                else:
                    total += v / ((1.0 + rate) ** (days_diff / 365.0))

            if math.isnan(total) or math.isinf(total):
                raise MeasureError("The result of XNPV is not a finite number.")
            if total == 0.0:
                return Decimal(0)
            return Decimal(int(total)) if total.is_integer() else Decimal(repr(total))
        if function == "CONCATENATEX":
            if _statistic_with_arithmetic(arguments[1]):
                # live Power BI (iteration 87): a statistic in arithmetic is a double, shown with 15 digits and a signed zero; the local decimals differ in the last digit
                raise MeasureError("CONCATENATEX of arithmetic with a statistical function is not exact in the local engine.")
            delimiter = "" if len(arguments) < 3 else dax_typed.to_text(evaluate(arguments[2], row_context, allow_text=True))
            order_spec: list[tuple[Any, bool]] = []  # (expression, descending); ASC is the default here
            position = 3
            while position < len(arguments):
                expression, descending = arguments[position], False
                position += 1
                if position < len(arguments):
                    direction = arguments[position]
                    if direction[0] == "table" and str(direction[1]).upper() in {"ASC", "DESC"}:
                        descending = str(direction[1]).upper() == "DESC"
                        position += 1
                    elif direction[0] in {"number", "boolean"}:
                        if direction[1] not in (0, 1):
                            raise MeasureError("Unexpected value for the ORDER argument. Use 0/FALSE/DESC for descending or 1/TRUE/ASC for ascending.")
                        descending = direction[1] == 0 or direction[1] is False
                        position += 1
                order_spec.append((expression, descending))
            read_nodes = [arguments[1], *(expression for expression, _d in order_spec)]
            topn_walk_nodes[id(arguments[0])] = read_nodes  # a TOPN argument is walked as this CONCATENATEX reads it
            try:
                context, iteration_rows = table_argument_value(arguments[0])
            finally:
                topn_walk_nodes.pop(id(arguments[0]), None)
            entries = []
            if not iteration_rows:
                refuse_foreign_columns_of_empty_iteration(context, *read_nodes)
            iteration_rows = dictionary_ordered_rows(arguments[0], context, iteration_rows, read_nodes)
            def order_value(expression: tuple[Any, ...], inner: tuple[Any, ...]) -> Any:
                value = evaluate(expression, inner, allow_text=True)
                if value is None and expression[0] == "reference" and not inner[0].get("derived"):
                    header = next((h for h in inner[0]["headers"] if h.casefold() == expression[2].casefold()), None)
                    if header is not None and inner[1].get(header) == "":
                        return ""  # an empty text is not a BLANK: Power BI orders BLANK before it
                return value

            outer_reads_before = outer_row_reads[0]
            for inner in iterate_rows(context, iteration_rows, "clear"):
                text = dax_typed.to_text(evaluate(arguments[1], inner, allow_text=True))
                entries.append(([order_value(expression, inner) for expression, _d in order_spec], text))
            if (
                outer_row_reads[0] != outer_reads_before
                or _contains_function_call(arguments[1], "OFFSET")  # relative to the current row: its order decides the text
                or (
                    _contains_function_call(arguments[1], "CALCULATE") and len({text for _key, text in entries}) > 1 and context.get("selected_columns")
                    and any(_contains_function_call(arguments[1], iterator) for iterator in ("SUMX", "AVERAGEX", "MINX", "MAXX", "COUNTX", "COUNTAX"))
                )
                or (_contains_function_call(arguments[1], "CALCULATETABLE") and len({text for _key, text in entries}) > 1 and arguments[0][0] == "table")  # the transition order of a table in the body is not measured
            ) and (
                not order_spec or len({row_key(item[0]) for item in entries}) != len(entries)
            ):
                # live Power BI (iteration 88): the walk order of an expression that reads a column of an enclosing row context through a nested iterator
                # differs from the one the local engine uses; only a total ORDER BY makes the text independent of it
                raise MeasureError("The order of a CONCATENATEX whose expression reads an enclosing row context is not modelled in the local engine.")
            for key_index in range(len(order_spec) - 1, -1, -1):
                column_keys = blank_aware_keys([item[0][key_index] for item in entries])
                try:
                    ranked = sorted(range(len(entries)), key=lambda i: column_keys[i], reverse=order_spec[key_index][1])
                except TypeError:  # keys that cannot be compared (a date with a number, ...)
                    raise MeasureError("The ORDER BY values of CONCATENATEX have types that cannot be compared in the local engine.") from None
                entries = [entries[i] for i in ranked]
            return delimiter.join(text for _, text in entries) if entries else None
        if function in _COLUMN_SCALAR_ARITY:
            value_context, value_column = resolve_table(arguments[0][1], arguments[0][2])
            refuse_one_to_one_blank_reader(value_context["id"], function)
            seen_values: dict[tuple[Any, ...], Any] = {}
            for row_index, source_row in enumerate(rows_by_table_id[value_context["id"]], 1):
                value = source_row.get(value_column)
                _reject_power_query_error(value, value_column, row_index)
                seen_values.setdefault(cell_key(ascii_fold(value) if isinstance(value, str) else value), value)
            if function == "HASONEVALUE":
                return len(seen_values) == 1
            if len(seen_values) != 1:
                return None if len(arguments) == 1 else evaluate(arguments[1], row_context, allow_text=True)
            only = next(iter(seen_values.values()))
            if only is None or only == "":
                return None if only is None else ""
            column_kind = str(value_context.get("column_types", {}).get(value_column, "text")).casefold()
            if column_kind in {"whole_number", "decimal_number", "decimal", "fixed_decimal", "currency", "number", "int64", "double"}:
                return dax_typed.text_to_number(cell_to_text(only))
            if column_kind in {"date", "datetime"}:
                return _cell_date_value(only, value_column, None)
            if column_kind == "boolean":
                return cell_to_text(only).strip().casefold() == "true"
            if column_kind != "text":
                raise MeasureError("SELECTEDVALUE supports text, number and True/False columns in the local engine.")
            return str(only)
        if function in {"MIN", "MAX"} and len(arguments) == 2:
            mixed_pair = date_number_mix(arguments[0], arguments[1])
            first = evaluate(arguments[0], row_context, allow_text=True)
            second = evaluate(arguments[1], row_context, allow_text=True)
            for operand in (first, second):
                if isinstance(operand, bool):
                    raise MeasureRuntimeError("Min or Max of booleans are not currently supported.")
            if dax_typed.is_non_finite(first) and first.is_nan():
                return first
            if dax_typed.is_non_finite(second) and second.is_nan():
                return second
            larger = dax_typed.compare(">", first, second)
            smaller = dax_typed.compare("<", first, second)
            picked = (first if larger else second) if function == "MAX" else (first if smaller else second)
            refuse_date_result(mixed_pair, picked)
            refuse_date_beside_number(arguments[:2], picked)
            return picked
        reference = arguments[0]
        if reference[0] != "reference" or len(reference) < 3:  # a table or other non-column argument is not a scalar source
            raise MeasureError(f"{function} needs a column reference in the local engine.")
        if function == "COUNTA" or (
            function == "COUNT"  # live Power BI: COUNT of a text column counts its non-blank values
            and str(resolve_table(reference[1], reference[2])[0].get("column_types", {}).get(resolve_table(reference[1], reference[2])[1], "")).casefold() == "text"
        ):
            context, actual = resolve_table(reference[1], reference[2])
            visible_rows = rows_by_table_id[context["id"]]
            if not visible_rows:
                return None
            count = 0
            for row_index, row in enumerate(visible_rows, 1):
                value = row.get(actual)
                _reject_power_query_error(value, actual, row_index)
                if value is not None:
                    count += 1
            return Decimal(count) if count else None  # Power BI returns blank for zero
        if function == "COUNTBLANK":
            context, actual = resolve_table(reference[1], reference[2])
            visible_rows = rows_by_table_id[context["id"]]
            blanks = 0
            for row_index, row in enumerate(visible_rows, 1):
                value = row.get(actual)
                _reject_power_query_error(value, actual, row_index)
                if value is None or value == "":
                    blanks += 1
            return Decimal(blanks) if blanks else None  # Power BI returns blank for zero
        if function in {"DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK"}:
            context, actual = resolve_table(reference[1], reference[2])
            rows = rows_by_table_id[context["id"]]
            if not rows:
                return None
            values: set[tuple[Any, ...]] = set()
            for row_index, row in enumerate(rows, 1):
                value = row.get(actual)
                _reject_power_query_error(value, actual, row_index)
                values.add(cell_key(ascii_fold(value) if isinstance(value, str) else value))
            if function == "DISTINCTCOUNTNOBLANK":
                values.discard(cell_key(None))
            return Decimal(len(values)) if values or function == "DISTINCTCOUNT" else None
        if function in {"MIN", "MAX", "COUNT"}:
            date_context, date_column = resolve_table(reference[1], reference[2])
            if str(date_context.get("column_types", {}).get(date_column, "")).casefold() in {"date", "datetime"}:
                moments = []
                visible = rows_by_table_id[date_context["id"]]
                for row_index, row in enumerate(visible, 1):
                    _reject_power_query_error(row.get(date_column), date_column, row_index)
                    moment = _cell_date_value(row.get(date_column), date_column, row_index)
                    if moment is not None:
                        moments.append(moment)
                if function == "COUNT":
                    return Decimal(len(moments)) if moments else None
                if not moments:
                    return None
                return (max if function == "MAX" else min)(moments)
        if function in {"MIN", "MAX"}:
            text_context, text_column = resolve_table(reference[1], reference[2])
            if str(text_context.get("column_types", {}).get(text_column, "")).casefold() == "text":
                texts = []
                for row_index, row in enumerate(rows_by_table_id[text_context["id"]], 1):
                    cell = row.get(text_column)
                    _reject_power_query_error(cell, text_column, row_index)
                    if cell is not None:  # an empty text value is a value, and the smallest one
                        texts.append(str(cell))
                if not texts:
                    return None
                return (max if function == "MAX" else min)(texts, key=dax_typed.text_key)
        if function in {"AVERAGEA", "MAXA", "MINA"}:
            a_context, a_column = resolve_table(reference[1], reference[2])
            a_type = str(a_context.get("column_types", {}).get(a_column, "")).casefold()
            if a_type in {"text", "boolean"}:
                # live Power BI (iteration 88): AVERAGEA / MAXA / MINA of a text column count every text, "5" and "TRUE" too, as 0 and leave out BLANKs;
                # True / False count as 1 / 0; with nothing left the result is BLANK
                counted = []
                for row_index, row in enumerate(rows_by_table_id[a_context["id"]], 1):
                    cell = row.get(a_column)
                    _reject_power_query_error(cell, a_column, row_index)
                    if cell is None:
                        continue
                    if a_type == "text":
                        counted.append(Decimal(0))
                    else:
                        spelled = cell_to_text(cell).strip().casefold()
                        if spelled not in {"true", "false"}:
                            raise MeasureError(f"Column {a_column!r} contains a value that is not True or False at row {row_index}.")
                        counted.append(Decimal(1 if spelled == "true" else 0))
                return dax_math.statistic(function, counted, None) if counted else None
        values = numeric_values(reference[2], reference[1])
        if function in dax_math.STAT_COLUMN_FUNCTIONS or function in dax_math.STAT_PERCENTILE_COLUMN:
            stat_context, stat_column = resolve_table(reference[1], reference[2])
            if str(stat_context.get("column_types", {}).get(stat_column, "")).casefold() in {"text", "boolean"}:
                raise MeasureError(f"{function} supports number columns in the local engine.")
            percentile = None
            if function in dax_math.STAT_PERCENTILE_COLUMN:
                percentile = dax_typed.to_number(evaluate(arguments[1], row_context))
            return dax_math.statistic(function, values, percentile)
        if function == "COUNT":
            context, actual = resolve_table(reference[1], reference[2])
            visible_rows = rows_by_table_id[context["id"]]
            return Decimal(len(values)) if values else None
        if not values:
            return None
        if function == "SUM": return sum(values, Decimal(0))
        if function == "MEDIAN":
            ordered = sorted(values)
            middle = len(ordered) // 2
            if len(ordered) % 2:
                return ordered[middle]
            return (ordered[middle - 1] + ordered[middle]) / Decimal(2)
        if function == "PRODUCT":
            with localcontext() as exact:
                exact.prec = _EXACT_PRECISION
                product = Decimal(1)
                for value in values:
                    product *= value
            if abs(product) > _DOUBLE_MAX:
                raise MeasureRuntimeError("The result is outside the supported numeric range.")
            return _checked_double(product)
        if function == "AVERAGE": return sum(values, Decimal(0)) / Decimal(len(values))
        if function == "MIN": return min(values)
        return max(values)

    def _single_cell_numeric_table_value(node: tuple[Any, ...]) -> Decimal | None:
        """When a single-cell table (ROW, {{...}}, DATATABLE) is the whole measure expression and holds a number."""
        if not isinstance(node, tuple) or not node:
            return None
        is_row = node[0] == "call" and node[1] == "ROW"
        is_datatable = node[0] == "call" and node[1] == "DATATABLE"
        is_nested_tc = (
            node[0] == "tableconstructor"
            and len(node[1]) == 1
            and isinstance(node[1][0], tuple)
            and bool(node[1][0])
            and node[1][0][0] == "tableconstructor"
        )
        if not (is_row or is_datatable or is_nested_tc):
            return None
        try:
            val = single_value_of(table_argument_value(node))
        except Exception:
            return None
        if isinstance(val, (int, Decimal)) and not isinstance(val, bool):
            return Decimal(val)
        return None

    def resolve(key: str) -> Decimal | bool | str | None:
        nonlocal current_home_table_id
        cache_key = (key, current_context)
        if cache_key in value_cache:
            return value_cache[cache_key]
        if key in resolving:
            raise MeasureError(f"Measure dependency cycle includes {by_name[key]['name']!r}.")
        resolving.add(key)
        previous_home_table_id = current_home_table_id
        current_home_table_id = str(
            by_name[key].get("home_table_id") or active_context["id"]
        )
        outer_variables = dict(variables)
        variables.clear()
        try:
            single_numeric = _single_cell_numeric_table_value(parsed[key])
            if single_numeric is not None:
                value = single_numeric
            else:
                value = evaluate(parsed[key])
        except (DecimalException, OverflowError) as exc:
            raise MeasureError(f"Measure {by_name[key]['name']!r} is outside the supported numeric range.") from exc
        except MeasureRuntimeError as exc:
            # live Power BI (iteration 88): STDEV.S / VAR.S (and the X forms) of fewer than two values are NaN, not an error.  Only a measure that is
            # that statistic itself (also under CALCULATE) shows NaN; inside any other expression Power BI treats the NaN differently per function.
            if getattr(exc, "sample_statistic_nan", False) and len(resolving) == 1 and _is_sample_statistic(parsed[key]):
                value = Decimal("NaN")
            else:
                raise
        finally:
            variables.update(outer_variables)
            current_home_table_id = previous_home_table_id
            resolving.remove(key)
        value_cache[cache_key] = value
        return value

    targets = None if measure_names is None else {name.casefold() for name in measure_names}
    selected = [item for item in definitions if targets is None or item["name"].casefold() in targets]
    missing = targets - set(by_name) if targets is not None else set()
    if missing:
        raise MeasureError(f"Measure {sorted(missing)[0]!r} does not exist.")
    results = {item["name"]: resolve(item["name"].casefold()) for item in selected}
    # Power BI checks the whole query when it compiles it, also the branches that never run; the engine's own errors come first
    reject_invalid_allexcept(parsed[item["name"].casefold()] for item in selected)
    if targets is not None:
        _reject_bare_columns_without_row_context(
            [(item, parsed[item["name"].casefold()]) for item in selected],
            list(parsed.values()),
            {
                str(ctx.get("name", "")).casefold(): {str(h).casefold() for h in ctx.get("headers", [])}
                for ctx in contexts_by_id.values()
            },
        )
    column_types_by_table = {
        str(ctx.get("name", "")).casefold(): {
            str(h).casefold(): str(ctx.get("column_types", {}).get(h, "")).casefold() for h in ctx.get("headers", [])
        }
        for ctx in contexts_by_id.values()
    }
    for item in selected:
        _reject_mismatched_comparison_types(parsed[item["name"].casefold()], column_types_by_table)
    return results
