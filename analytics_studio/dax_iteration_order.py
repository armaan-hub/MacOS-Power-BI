"""The order in which Power BI walks a table: dictionary order, not source-row order.

Measured against Power BI Desktop 2.157.879.0 (tools/parity/dax_battery_concatenatex_order.json and 93 probes on 29 table
shapes in tests/fixtures_concatenatex_order.json): an iterator such as CONCATENATEX visits the distinct combinations of
the columns its expression (and ORDER BY keys) read, each repeated by its row count. Inside one column BLANK comes first,
numbers and dates ascend, FALSE precedes TRUE and text keeps the order of its first appearance in the source rows (ASCII
case-insensitive). With several columns the LATER table column is the major key. When the column set is wide the engine
falls back to plain source order. That switch is VertiPaq-internal; `grouped` below is a fit of it to the measured shapes
and is deliberately conservative: when unsure the rows stay in source order, which is what the app did before.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from math import gcd
from typing import Any, Callable, Iterable, Sequence

from analytics_studio.dax_dates import DaxDateTime
from analytics_studio.power_query_values import ascii_fold

# Nodes whose references belong to some other row context (a nested table, a lookup): the columns this iterator reads
# cannot be listed from the syntax alone.
_OPAQUE_KINDS = frozenset({"table", "table_call", "tableconstructor", "in"})  # a VAR holds a value fixed outside the row
CROSS_TABLE_CALLS = frozenset({"RELATED", "RELATEDTABLE", "EARLIER", "EARLIEST", "LOOKUPVALUE", "USERELATIONSHIP"})

# A numeric or date column is walked in value order while (dense range) x (rows + 3) stays under this; fitted on probes.
# The range of whole numbers is divided by their gcd; the range of dates (in days) is not.
_SINGLE_COLUMN_BUDGET = 8200
# Several columns are walked in dictionary order while (product of their distinct counts) x (rows) stays under this; a date
# counts by its range in days, and a set with a date stays under the tighter limit (probed on date spans of 30 to 365 days).
_COMBINATION_BUDGET = 3100
_DATE_COMBINATION_BUDGET = 2500
# Fractional digits a double may carry and still be treated as a regular range.
_MAX_DECIMALS = 4


@dataclass
class Plan:
    """How a table expression is walked: `dedup` tables (SUMMARIZE, VALUES/ALL/DISTINCT of columns) are always walked in
    dictionary order over ALL their columns; `computed` maps an added column to its expression, and every `eager`
    expression (ADDCOLUMNS) pulls its source columns into the combination whether or not the iterator reads them."""

    dedup: bool = False
    computed: dict[str, Any] = field(default_factory=dict)
    eager: list[Any] = field(default_factory=list)
    projects: bool = False  # SELECTCOLUMNS: the columns it reads are resolved in the table it selects from


def plan(node: Any, bound: Callable[[str], Any] = lambda name: None) -> Plan | None:
    """The Plan of a table expression whose walk order was measured, or None (UNION, CROSSJOIN, TOPN, DISTINCT(table), ...).

    `bound` gives the expression a VAR was declared with, so a table held in a VAR is walked as that expression is."""
    if not isinstance(node, tuple) or not node:
        return None
    if node[0] == "var":
        held = bound(node[1])
        return plan(held, bound) if held is not None else None
    if node[0] == "table":
        return Plan()
    if node[0] == "table_call":  # VALUES(x) and DISTINCT(x) carry their single argument directly
        name, arguments = node[1], (node[2],)
    elif node[0] == "call" and node[2]:
        name, arguments = node[1], node[2]
    else:
        return None
    if name in {"FILTER", "CALCULATETABLE"}:
        return None if any(_mentions_outer_row(argument) for argument in arguments[1:]) else plan(arguments[0], bound)
    if name == "SELECTCOLUMNS":
        if plan(arguments[0], bound) is None:
            return None
        chosen = Plan(projects=True)
        position = 1
        while position < len(arguments):
            if arguments[position][0] == "reference":  # a bare column reference keeps its own name
                chosen.computed[str(arguments[position][2]).casefold()] = arguments[position]
                position += 1
            elif arguments[position][0] == "string" and position + 1 < len(arguments):
                chosen.computed[str(arguments[position][1]).casefold()] = arguments[position + 1]
                position += 2
            else:
                return None
        return chosen
    if name == "ADDCOLUMNS":
        inner = plan(arguments[0], bound)
        if inner is None or inner.projects:
            return None
        for position in range(1, len(arguments) - 1, 2):
            if arguments[position][0] != "string":
                return None
            inner.computed[str(arguments[position][1]).casefold()] = arguments[position + 1]
            inner.eager.append(arguments[position + 1])
        return inner
    if name == "SUMMARIZE":
        return Plan(dedup=True) if plan(arguments[0], bound) is not None else None
    if name in {"VALUES", "ALL", "DISTINCT"}:
        if all(argument[0] == "reference" for argument in arguments):
            return Plan(dedup=True)
        if name != "DISTINCT" and len(arguments) == 1 and arguments[0][0] == "table":
            return Plan()  # every row of the table, as the table itself
    return None


def _mentions_outer_row(node: Any) -> bool:
    """A predicate that reaches into an enclosing row context (EARLIER); the walk order of such a filter is not measured."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in {"EARLIER", "EARLIEST"}:
        return True
    return any(_mentions_outer_row(child) for child in node if isinstance(child, tuple))


ALL_COLUMNS = ("", "*")  # a context transition (CALCULATE, a measure) makes every column of the iterated table count


def columns_read(
    nodes: Iterable[Any],
    is_foreign_call: Callable[[str], bool],
    is_nested_call: Callable[[str], bool] = lambda name: False,
    is_measure: Callable[[str], bool] = lambda name: False,
) -> list[tuple[str, str]] | None:
    """(table, column) of every column of the ITERATED row that `nodes` read, or None when the syntax hides some of them.

    A column inside a nested iterator or aggregation belongs to that inner row, not to this one; only EARLIER/EARLIEST (and a
    context transition, which reads every column: ALL_COLUMNS) reach the outer row."""
    found: list[tuple[str, str]] = []

    def inner(node: Any) -> bool:
        if not isinstance(node, tuple) or not node:
            return True
        kind = node[0]
        if kind == "reference":
            if not node[1] and is_measure(node[2]):
                found.append(ALL_COLUMNS)
            return True
        if kind in _OPAQUE_KINDS - {"table", "tableconstructor"}:
            return False
        if kind == "call":
            if node[1] in {"EARLIER", "EARLIEST"} and node[2] and node[2][0][0] == "reference":
                found.append((node[2][0][1], node[2][0][2]))
                return True
            if node[1] in {"CALCULATE", "CALCULATETABLE"}:
                found.append(ALL_COLUMNS)
                return True
            if is_foreign_call(node[1]):
                return False
        children = node if isinstance(node[0], tuple) else node[1:]
        return all(inner(child) for child in children if isinstance(child, tuple))

    def walk(node: Any) -> bool:
        if not isinstance(node, tuple) or not node:
            return True
        kind = node[0]
        if kind == "reference":
            if not node[1] and is_measure(node[2]):
                found.append(ALL_COLUMNS)
            else:
                found.append((node[1], node[2]))
            return True
        if kind in _OPAQUE_KINDS:
            return False
        if kind == "call":
            if node[1] in {"CALCULATE", "CALCULATETABLE"}:
                found.append(ALL_COLUMNS)
                return True
            if is_foreign_call(node[1]):
                return False
            if is_nested_call(node[1]):
                return inner(node)
        children = node if isinstance(node[0], tuple) else node[1:]
        return all(walk(child) for child in children if isinstance(child, tuple))

    return found if all(walk(node) for node in nodes) else None


class Profile:
    """How one source column is encoded: its text dictionary, distinct count and the size of its value range."""

    def __init__(self, values: Sequence[Any]) -> None:
        present = [v for v in values if v is not None]
        self.is_text = bool(present) and isinstance(present[0], str)
        self.is_bool = bool(present) and isinstance(present[0], bool)
        self.is_date = bool(present) and isinstance(present[0], (DaxDateTime, datetime, date))
        self._rank: dict[str, int] = {}
        if self.is_text:
            for value in present:
                self._rank.setdefault(ascii_fold(value), len(self._rank))
        self.distinct = len({None if v is None else ascii_fold(v) if self.is_text else v for v in values})
        self.fractional = any(isinstance(v, Decimal) and v.is_finite() and v != v.to_integral_value() for v in present)
        self.size: int | None = self.distinct if self.is_text or self.is_bool else _dense_range(present, self.is_date)
        # a datetime with a time of day has no regular range of days; VALUES/ALL of it still walks by its steps of time
        self.timed = self.is_date and self.size is None
        self.time_steps = _time_steps(present) if self.timed else None

    @property
    def is_numeric(self) -> bool:
        return not (self.is_text or self.is_bool)

    def key(self, value: Any) -> tuple[int, Any]:
        if value is None:
            return (0, 0)
        if self.is_text:
            return (1, self._rank.get(ascii_fold(value), len(self._rank)))
        return (1, value)


def _time_steps(values: list[Any]) -> int | None:
    """(max - min) / gcd + 1 over the values counted in whole seconds; None when they are not whole seconds."""
    seconds: list[int] = []
    for value in values:
        if isinstance(value, Decimal):
            scaled = value * 86400
        elif isinstance(value, datetime):
            scaled = Decimal(value.toordinal() * 86400 + value.hour * 3600 + value.minute * 60 + value.second)
        else:
            scaled = Decimal(value.toordinal() * 86400)
        if not scaled.is_finite() or abs(scaled - scaled.to_integral_value()) > Decimal("0.001"):
            return None
        seconds.append(int(scaled.to_integral_value()))
    low, step = min(seconds), 0
    for second in seconds:
        step = gcd(step, second - low)
    return (max(seconds) - low) // (step or 1) + 1


def _dense_range(values: list[Any], is_date: bool) -> int | None:
    """Dense range of the values: whole numbers (max - min) / gcd + 1; dates (max - min) in days + 1; None when irregular."""
    if not values:
        return 1
    numbers: list[int] = []
    for value in values:
        if is_date:
            if isinstance(value, Decimal):
                if value != value.to_integral_value():  # a time of day: not a regular range of days
                    return None
                numbers.append(int(value))
            elif isinstance(value, datetime) and value.time() != datetime.min.time():
                return None
            else:
                numbers.append((value.date() if isinstance(value, datetime) else value).toordinal())
        elif isinstance(value, Decimal) and value.is_finite():
            scaled = value.scaleb(_MAX_DECIMALS)
            if scaled != scaled.to_integral_value():  # more fractional digits than are modelled
                return None
            numbers.append(int(scaled))
        else:
            return None
    low = min(numbers)
    step = 0
    for number in numbers:
        step = gcd(step, number - low)
    return (max(numbers) - low) // (1 if is_date else step or 1) + 1


def grouped(row_count: int, profiles: Sequence[Profile], dedup: bool = False) -> bool:
    """True when Power BI walks these columns in dictionary order, False when it keeps source-row order.

    `dedup` is a table that already holds each combination once (SUMMARIZE, VALUES, ALL of columns): only the per-column
    test applies to it, a lone date column always passes it, and a datetime with a time of day passes it alone while its
    steps of time stay in range."""
    for profile in profiles:
        if dedup and profile.timed:
            if len(profiles) > 1 or profile.time_steps is None or profile.time_steps * (row_count + 3) > _SINGLE_COLUMN_BUDGET:
                return False
            continue
        if dedup and profile.is_date and len(profiles) == 1:  # VALUES/ALL of one date column always ascend; with others the range counts
            continue
        if profile.size is None or (profile.is_numeric and profile.size * (row_count + 3) > _SINGLE_COLUMN_BUDGET):
            return False
    if len(profiles) == 1 or dedup:
        return True
    if any(profile.fractional for profile in profiles):  # a double beside another column
        return False
    if len(profiles) >= 3 and any(profile.is_date for profile in profiles):  # not measured: keep source order
        return False
    combinations = 1
    for profile in profiles:
        combinations *= profile.size if profile.is_date else profile.distinct
    budget = _DATE_COMBINATION_BUDGET if any(profile.is_date for profile in profiles) else _COMBINATION_BUDGET
    return combinations * row_count <= budget


def heap_top(count: int, items: Sequence[Any], better: Callable[[Any, Any], bool]) -> list[Any]:
    """The `count` best `items` as the array of the binary heap Power BI builds for TOPN (worst kept item at the root).

    `better(a, b)` is True when a should replace b. Items arrive in walk order; the first `count` fill the heap by
    sift-up, each later one that beats the root replaces it and sifts down. The array order, not a sorted order, is what
    the rows are returned in (measured: TOPN(3, Quantity 0..5) walks out as 3,5,4)."""
    heap: list[Any] = []

    def sift_up(index: int) -> None:
        while index > 0:
            parent = (index - 1) // 2
            if not better(heap[parent], heap[index]):
                return
            heap[parent], heap[index] = heap[index], heap[parent]
            index = parent

    def sift_down(index: int) -> None:
        while True:
            worst = index
            for child in (2 * index + 1, 2 * index + 2):
                if child < len(heap) and better(heap[worst], heap[child]):
                    worst = child
            if worst == index:
                return
            heap[index], heap[worst] = heap[worst], heap[index]
            index = worst

    for item in items:
        if len(heap) < count:
            heap.append(item)
            sift_up(len(heap) - 1)
        elif better(item, heap[0]):
            heap[0] = item
            sift_down(0)
    return heap
