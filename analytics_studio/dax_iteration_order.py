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
# Task 77 (live Power BI, topn-data-67 grid, dataset d4): VALUES / DISTINCT / UNION(VALUES) of one whole-number column walk in value order up to a
# range of 998 over 12 rows (space 14,970), while a TOPN read of the same column keeps the storage order at that size (the 8,200 budget above).
# 14,970 is the largest measured sorted space for a deduplicated single column; no larger size is measured, so none is assumed.
_DEDUP_SINGLE_COLUMN_BUDGET = 14970
# Several columns are walked in dictionary order while (product of their distinct counts) x (rows) stays under this; a date
# counts by its range in days, and a set with a date stays under the tighter limit (probed on date spans of 30 to 365 days).
# Task 67 (live Power BI, six Facts row sets of 6 to 12 rows, 1 to 3 listed columns, ALLEXCEPT / GROUPBY / SUMMARIZECOLUMNS): a table of listed columns
# comes out in dictionary order (last table column the major key) while its dense key space (product of the value-range sizes of the columns) is small
# for the number of rows, and in storage order when the space is large. The measured boundary is not one number: a space of 792 over 6 rows is storage
# order, 2,994 over 12 rows is still sorted. Only the measured points are used, as (space, rows): a space no larger than a measured sorted one over no
# more rows is sorted; a space no smaller than a measured storage-order one over no more rows is storage order; anything else is not decided.
_MEASURED_SORTED = ((396, 6), (429, 7), (567, 9), (2994, 12))
_MEASURED_STORAGE = ((792, 6), (8982, 12))
# Task 68 (live Power BI, SUMMARIZE ... ROLLUP / ADDMISSINGITEMS(SUMMARIZE) under an outer filter, datasets d7 and d9): the scan over the group columns plus the
# filtered columns was still sorted at a space of 840 over 8 rows, 1,596 over 10 rows and (dataset d10) 36 over 5 rows, and (round 3, datasets d12 and d14) 2,250 over 11 rows (sorted); 7,600 over 14 rows was storage order. These points apply to that scan only.
# Beyond them the scan has no storage point of its own: the groups of a filtered scan are then refused where they are read in order (never the (8982, 12) storage point)
_MEASURED_SORTED_SCAN = _MEASURED_SORTED + ((840, 8), (1596, 10), (36, 5), (2250, 11))
_MEASURED_STORAGE_SCAN = ((792, 6), (7600, 14))  # the detail scan of d14 (Sales x Quantity x Region = 7,600 over 14 rows) came back in storage order
# Task 69 (live Power BI, order audit 4 grids t69a / t69b and nine datasets, SELECTCOLUMNS(Facts, "d", DATE(..) - Quantity, "r", <column>) read through [d]): the projected
# columns are walked in dictionary order (the later table column the major key) while their dense key space (product of the value-range sizes) is small for the rows, and in
# storage order when it is large: sorted at (space, rows) = (8, 5), (18, 6), (210, 8), (237, 12) and the many smaller ones they cover; storage order at (730, 13), (936, 16)
# (and (750, 11), (1900, 14), (4921, 10), (78842, 12), which those cover). A space between them is not decided.
_PROJECTION_SORTED = ((8, 5), (18, 6), (210, 8), (237, 12))
_PROJECTION_STORAGE = ((730, 13), (936, 16))
# DISTINCT(SELECTCOLUMNS(..)) over one source column: walked by that column in dictionary order, a value where its first source row is; sorted up to a range of 998 over 12 rows
_PROJECTION_DISTINCT_BUDGET = 14970
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
    scanned: bool = False  # SUMMARIZE of a table: an outer filter on another column joins the sort key of the groups (measured), which is not modelled
    measured_space: bool = False  # ALLEXCEPT / GROUPBY / SUMMARIZECOLUMNS: dictionary order only inside the measured key space (multi_column_order)


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
    if name == "TABLEOF":
        return Plan()
    if name == "DISTINCT" and len(arguments) == 1 and isinstance(arguments[0], tuple) and arguments[0][:1] in {("call",), ("table_call",)}:
        # Task 69 (live Power BI, order audit 4 grid, part C): DISTINCT of a SELECTCOLUMNS walks the distinct rows in the order of the columns the
        # projection reads (DISTINCT(SELECTCOLUMNS(Facts, "y", YEAR(DATE(2020 + Quantity, 1, 1)))) comes out 2020, 2021, ... ascending)
        inner = plan(arguments[0], bound)
        if inner is not None and inner.projects:
            return Plan(dedup=True, projects=True, computed=inner.computed, eager=inner.eager)
    if name == "KEEPFILTERS" and len(arguments) == 1:
        return plan(arguments[0], bound)  # live Power BI (Part C review): the wrapper does not change the walk order
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
        # Task 69 (live Power BI, order audit 4 grid, part D): once one projection is computed, every projected column joins the walk key, as
        # ADDCOLUMNS does: SELECTCOLUMNS(Facts, "d", DATE(..) - Quantity, "r", Region) walks Region first, then Quantity. Bare columns alone keep
        # the columns the iterator reads (measured: SELECTCOLUMNS(Facts, "a", Region, "b", Note) read through [a] walks Region alone).
        if any(value[0] != "reference" for value in chosen.computed.values()):
            chosen.eager = list(chosen.computed.values())
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
        if any(isinstance(arg, tuple) and arg[0] == "call" and arg[1] in {"ROLLUP", "ROLLUPGROUP"} for arg in arguments[1:]):
            return None
        return Plan(dedup=True, scanned=arguments[0][0] == "table", measured_space=arguments[0][0] == "table") if plan(arguments[0], bound) is not None else None
    if name in {"VALUES", "ALL", "DISTINCT"}:
        if all(argument[0] == "reference" for argument in arguments):
            return Plan(dedup=True)
        if name != "DISTINCT" and len(arguments) == 1 and arguments[0][0] == "table":
            return Plan()  # every row of the table, as the table itself
    if name == "GROUPBY" and len(arguments) >= 2 and plan(arguments[0], bound) is not None:
        groups = []  # the group columns come first, then the name / expression pairs
        for argument in arguments[1:]:
            if argument[0] != "reference":
                break
            groups.append(argument)
        if groups:
            return Plan(dedup=True, measured_space=True)  # Task 67 (live Power BI, audit2 grid): GROUPBY lists its groups in the dictionary order of the group columns, like SUMMARIZE
    if name == "SUMMARIZECOLUMNS" and arguments and arguments[0][0] == "reference":
        groups = 0
        while groups < len(arguments) and arguments[groups][0] == "reference":
            groups += 1
        rest = arguments[groups:]  # then name / measure pairs
        if len(rest) % 2 == 0 and all(rest[i][0] == "string" for i in range(0, len(rest), 2)):
            # Task 67 (live Power BI, audit2 + held-out grids): SUMMARIZECOLUMNS walks its combinations in dictionary order of the group columns, the
            # last table column the major key, with or without measure columns; an outer filter on another column does not join the key
            return Plan(dedup=True, measured_space=True)
    if name == "ALLEXCEPT" and len(arguments) >= 2 and arguments[0][0] == "table" and all(argument[0] == "reference" for argument in arguments[1:]):
        # Task 67 (live Power BI, three Facts datasets): ALLEXCEPT lists the other columns of the table in the dictionary order of those columns
        # (last table column the major key, BLANK first, text first-seen, numbers sorted) inside the measured key space; see allexcept_in_dictionary_order
        return Plan(dedup=True, measured_space=True)
    if name == "ALLSELECTED" and len(arguments) == 1 and arguments[0][0] == "table":
        return Plan()  # Task 51 (live Power BI 2026-11-05): ALLSELECTED(table) is walked as ALL(table) is
    return None


def _order_expressions(arguments: Sequence[Any]) -> tuple[Any, ...]:
    """The expressions of an ORDERBY argument list, without the ASC / DESC (or 0 / 1) token that follows each one."""
    kept: list[Any] = []
    position = 0
    while position < len(arguments):
        kept.append(arguments[position])
        position += 1
        if position < len(arguments) and (arguments[position][0] == "table" and str(arguments[position][1]).upper() in {"ASC", "DESC"} or arguments[position][0] in {"number", "boolean"}):
            position += 1
    return tuple(kept)


def filtered_whole_table(node: Any, table_name: str) -> bool:
    """FILTER(ALL(table), predicate) or FILTER(table, predicate) of the walked table, whose predicate reaches no outer row."""
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] == "FILTER" and isinstance(node[2], tuple) and len(node[2]) == 2):
        return False
    source, predicate = node[2]
    if _mentions_outer_row(predicate):
        return False
    if isinstance(source, tuple) and source[:1] == ("table",):
        return str(source[1]).casefold() == str(table_name).casefold()
    return isinstance(source, tuple) and len(source) == 3 and source[0] == "call" and source[1] == "ALL" and len(source[2]) == 1 and source[2][0][:1] == ("table",) and str(source[2][0][1]).casefold() == str(table_name).casefold()


def rankx_walk(nodes: Iterable[Any], table_name: str) -> tuple[list[Any], list[Any]]:
    """Task 70 (live Power BI, rankx audit grid t70a): for every RANKX in `nodes` that ranks the rows of `table_name` through ALL / ALLSELECTED /
    VALUES / DISTINCT of its columns (or the table itself), returns the nodes with that table argument replaced by a number (the table is not
    read by the iterator, and a table_call would hide the reads of the rest) and the RANKX expression, which the iterator DOES read in its walk:
    a body reading Facts[Note] walks the rows blank first, then the text in first-seen order, although the RANKX reads them row by row."""
    bodies: list[Any] = []

    def ranks_walked_table(ranked: Any) -> bool:
        if isinstance(ranked, tuple) and len(ranked) == 3 and ranked[0] in {"call", "table_call"} and ranked[1] in {"ALL", "ALLSELECTED", "VALUES", "DISTINCT"}:
            # ALL(table), ALL(Table[column]), VALUES(Table[column]): every argument a column (or the table) of the walked table; VALUES and
            # DISTINCT of one column carry the argument directly (a table_call)
            arguments = ranked[2] if ranked[0] == "call" and isinstance(ranked[2], tuple) else (ranked[2],) if ranked[0] == "table_call" else ()
            return bool(arguments) and all(isinstance(a, tuple) and a[:1] in {("reference",), ("table",)} and str(a[1]).casefold() == str(table_name).casefold() for a in arguments)
        return isinstance(ranked, tuple) and len(ranked) == 2 and ranked[0] == "table" and str(ranked[1]).casefold() == str(table_name).casefold()

    def rebuild(node: Any) -> Any:
        if not isinstance(node, tuple) or not node:
            return node
        if node[0] == "call" and node[1] == "RANKX" and isinstance(node[2], tuple) and len(node[2]) >= 2 and ranks_walked_table(node[2][0]):
            bodies.append(node[2][1])
            return ("call", "RANKX", (("number", 0), *node[2][1:]), *node[3:])
        # Task 71 (live Power BI, rank audit grid t71a, Part C): RANKX over FILTER(ALL(table), predicate) walks the rows by the columns its expression and its
        # explicit value argument read (RANKX(FILTER(ALL(Facts), Quantity > 1), Sales, Sales, ASC) walks by Sales); the ORDER token is not read
        if node[0] == "call" and node[1] == "RANKX" and isinstance(node[2], tuple) and len(node[2]) >= 3 and filtered_whole_table(node[2][0], table_name):
            bodies.extend(argument for argument in node[2][1:3] if isinstance(argument, tuple) and argument[0] != "table")
            return ("call", "RANKX", (("number", 0),), *node[3:])
        # Task 71 (live Power BI, rank audit grid t71a, Part C): RANK and ROWNUMBER over ALL / ALLSELECTED / VALUES of the walked table walk the rows
        # by the columns of their ORDERBY (and PARTITIONBY) arguments, as the RANKX body does; the relation is replaced by a number as above
        if node[0] == "call" and node[1] in {"RANK", "ROWNUMBER"} and isinstance(node[2], tuple) and node[2]:
            index = 1 if node[1] == "RANK" and node[2][0][0] == "table" and str(node[2][0][1]).upper() in {"DENSE", "SKIP"} else 0
            relation = node[2][index] if len(node[2]) > index else None
            whole_table = isinstance(relation, tuple) and len(relation) == 3 and relation[0] == "call" and relation[1] in {"ALL", "ALLSELECTED"} and len(relation[2]) == 1 and relation[2][0][0] == "table"
            # measured for relations of one or two columns (rank audit grid t71a); a relation of three columns or more keeps the walk it had
            narrow = isinstance(relation, tuple) and len(relation) == 3 and relation[0] == "call" and len({str(a[2]).casefold() for a in relation[2] if a[0] == "reference"}) <= 2
            if relation is not None and not whole_table and narrow and ranks_walked_table(relation):
                # the walk reads the columns of the relation (the current row is found in it by them) and the ORDERBY and PARTITIONBY expressions; the ties and
                # blanks keywords and the ASC / DESC tokens are not read
                bodies.extend(a for a in relation[2] if isinstance(a, tuple) and a[0] == "reference")
                kept = []
                for argument in node[2]:
                    if isinstance(argument, tuple) and argument[:2] == ("call", "ORDERBY") and isinstance(argument[2], tuple):
                        kept.append(("call", "ORDERBY", _order_expressions(argument[2])))
                    elif isinstance(argument, tuple) and argument[:2] == ("call", "PARTITIONBY"):
                        kept.append(argument)
                return ("call", node[1], tuple(kept))
        return tuple(rebuild(child) if isinstance(child, tuple) else child for child in node)

    rebuilt = [rebuild(node) for node in nodes]
    return rebuilt, bodies


def _mentions_outer_row(node: Any) -> bool:
    """A predicate that reaches into an enclosing row context (EARLIER); the walk order of such a filter is not measured."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in {"EARLIER", "EARLIEST"}:
        return True
    return any(_mentions_outer_row(child) for child in node if isinstance(child, tuple))


ALL_COLUMNS = ("", "*")  # a context transition (CALCULATE, a measure) makes every column of the iterated table count


def _constant_condition(node: Any) -> bool | None:
    """True / False for an IF condition written as a literal (TRUE(), FALSE(), a number, BLANK()), else None."""
    if not isinstance(node, tuple) or not node:
        return None
    if node[0] == "boolean":
        return bool(node[1])
    if node[0] == "number":
        return node[1] != 0
    if node[0] == "blank" or (node[0] == "call" and node[1] == "BLANK" and not node[2]):
        return False
    if node[0] == "call" and node[1] in {"TRUE", "FALSE"} and not node[2]:
        return node[1] == "TRUE"
    if node[0] == "comparison" and node[1] == "=" and len(node) == 4 and node[2][0] == "number" and node[3][0] == "number":
        return node[2][1] == node[3][1]  # Task 63 (live Power BI): IF(1=0, x, y) is folded to y like IF(FALSE(), x, y), so the dead branch's columns are not read
    return None


def _folded_branch(node: Any) -> tuple[Any, ...] | None:
    """The branch an IF / IF.EAGER with a literal condition keeps (live Power BI, Task 10 review: the other branch is folded away before
    the table is walked, so only the columns of the kept branch decide the order); () when the kept branch is the implicit BLANK."""
    if isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] == "SWITCH" and len(node[2]) == 4:
        # Task 63 (live Power BI, held-out grid: exact on 17 of 17 stored-table rows): SWITCH(TRUE(), FALSE(), x, y) folds to y like IF(FALSE(), x, y)
        if _constant_condition(node[2][0]) is True and _constant_condition(node[2][1]) is False:
            return node[2][3]
        return None
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] in {"IF", "IF.EAGER"} and len(node[2]) >= 2):
        return None
    folded = _constant_condition(node[2][0])
    if folded is None:
        return None
    if folded:
        return node[2][1]
    return node[2][2] if len(node[2]) > 2 else ()


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
            branch = _folded_branch(node)
            if branch is not None:
                return inner(branch) if branch else True
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
            branch = _folded_branch(node)
            if branch is not None:
                return walk(branch) if branch else True
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


def grouped(row_count: int, profiles: Sequence[Profile], dedup: bool = False, beside_doubles: bool = False) -> bool:
    """True when Power BI walks these columns in dictionary order, False when it keeps source-row order.

    `dedup` is a table that already holds each combination once (SUMMARIZE, VALUES, ALL of columns): only the per-column
    test applies to it, a lone date column always passes it, and a datetime with a time of day passes it alone while its
    steps of time stay in range.  `beside_doubles` lifts the refusal of a fractional column beside ONE other column: a MAXX / MINX
    walk over a stored table with a NaN body (Task 63) keeps the dictionary order there (measured on the Facts sample); with three
    columns it keeps the source order, which is not modelled, so the refusal stays."""
    for profile in profiles:
        if dedup and profile.timed:
            if len(profiles) > 1 or profile.time_steps is None or profile.time_steps * (row_count + 3) > _SINGLE_COLUMN_BUDGET:
                return False
            continue
        if dedup and profile.is_date and len(profiles) == 1:  # VALUES/ALL of one date column always ascend; with others the range counts
            continue
        budget = _DEDUP_SINGLE_COLUMN_BUDGET if dedup and len(profiles) == 1 else _SINGLE_COLUMN_BUDGET
        if profile.size is None or (profile.is_numeric and profile.size * (row_count + 3) > budget):
            return False
    if len(profiles) == 1 or dedup:
        return True
    if any(profile.fractional for profile in profiles) and (not beside_doubles or len(profiles) != 2):  # a double beside another column (beside_doubles: measured for two columns only)
        return False
    if len(profiles) >= 3 and any(profile.is_date for profile in profiles):  # not measured: keep source order
        return False
    combinations = 1
    for profile in profiles:
        combinations *= profile.size if profile.is_date else profile.distinct
    budget = _DATE_COMBINATION_BUDGET if any(profile.is_date for profile in profiles) else _COMBINATION_BUDGET
    return combinations * row_count <= budget


def projection_order(row_count: int, profiles: Sequence[Profile]) -> bool | None:
    """True / False / None (not decided) for the walk of the columns a SELECTCOLUMNS with a computed projection holds (see _PROJECTION_SORTED)."""
    space = 1
    for profile in profiles:
        if profile.size is None:
            return False  # a column with no regular range (a fractional double): storage order, as measured
        space *= profile.size
    if any(space <= measured and row_count >= rows for measured, rows in _PROJECTION_SORTED):
        return True
    if any(space >= measured and row_count <= rows for measured, rows in _PROJECTION_STORAGE):
        return False
    return None


# Task 71 (live Power BI, rank audit grids t71a / t71b on Facts and t71d on datasets d2, d5, d7, d10, d13, d16: CONCATENATEX over RANK / ROWNUMBER of ALL(column,
# column), 120 shapes): the rows are walked by the projection's columns in dictionary order (the later table column the major key) while the dense key space (product of
# the value-range sizes) is small for the rows, and in source order when it is large: sorted at (space, rows) = (24, 6), (12, 5), (140, 8) and the smaller ones they cover (a
# fractional double included: 63 over 9 rows); source order at (132, 6), (264, 6), (292, 13). A space between the two is not decided.
_RANK_WALK_SORTED = ((24, 6), (12, 5), (140, 8))
_RANK_WALK_STORAGE = ((132, 6), (292, 13))


def rank_walk_order(row_count: int, profiles: Sequence[Profile]) -> bool | None:
    """True / False / None (not decided) for the walk of the columns a RANK / ROWNUMBER relation reads (see _RANK_WALK_SORTED); None also when a column has no regular range."""
    space = 1
    for profile in profiles:
        if profile.size is None:
            return None
        space *= profile.size
    if any(space <= measured and row_count >= rows for measured, rows in _RANK_WALK_SORTED):
        return True
    if any(space >= measured and row_count <= rows for measured, rows in _RANK_WALK_STORAGE):
        return False
    return None


def rank_windows(nodes: Iterable[Any]) -> bool:
    """Whether `rankx_walk` rewrote a RANK / ROWNUMBER of `nodes` (one left with only its ORDERBY / PARTITIONBY arguments): the walk reads that window's columns."""
    def found(node: Any) -> bool:
        if not isinstance(node, tuple) or not node:
            return False
        if node[0] == "call" and node[1] in {"RANK", "ROWNUMBER"} and isinstance(node[2], tuple) and node[2] and all(isinstance(a, tuple) and a[:2] in {("call", "ORDERBY"), ("call", "PARTITIONBY")} for a in node[2]):
            return True
        return any(found(child) for child in node if isinstance(child, tuple))
    return any(found(node) for node in nodes)


def multi_column_order(row_count: int, profiles: Sequence[Profile], scan: bool = False) -> bool | None:
    """True when the columns of an ALLEXCEPT / GROUPBY / SUMMARIZECOLUMNS table are walked in dictionary order, False when they keep the storage
    order, None when the key space is not covered by a measured point. Dates are not covered: they keep the older `grouped` test."""
    space = 1
    for profile in profiles:
        if profile.size is None:
            return False  # a column with no regular range: the order the app always used
        space *= profile.size
    if any(space <= measured and row_count >= rows for measured, rows in (_MEASURED_SORTED_SCAN if scan else _MEASURED_SORTED)):
        return True
    if any(space >= measured and row_count <= rows for measured, rows in (_MEASURED_STORAGE_SCAN if scan else _MEASURED_STORAGE)):
        return False
    return None


# Task 77 (live Power BI, topn-data-67 grid on datasets d2 to d18): the rows a CONCATENATEX walks through TOPN(n, table, key) come out of the
# heap in dictionary order of the two columns it reads while (space) x (rows) is small, and in storage order when it is large. The space is the
# product of the two columns' value ranges (dense range for numbers, distinct count for text). Measured on 900 TOPN rows of 17 row sets: sorted at
# 3,410 (10 rows), storage at 3,796 (13 rows); no measured row lies between. A fractional column or a date keeps the older grouped test.
_TOPN_PAIR_SORTED_SPACE = 3410
_TOPN_PAIR_STORAGE_SPACE = 3796


def topn_pair_applies(profiles: Sequence[Profile]) -> bool:
    """True when the two-column TOPN walk rule is measured for these columns (whole numbers or text, no date, no fractional double)."""
    return len(profiles) == 2 and all(profile.size is not None and not profile.is_date and not profile.fractional for profile in profiles)


def topn_pair_order(row_count: int, profiles: Sequence[Profile]) -> bool | None:
    """True when the TOPN walk is in dictionary order, False when in storage order, None when the space is between the measured points (refuse)."""
    space = profiles[0].size * profiles[1].size * row_count  # type: ignore[operator]
    if space <= _TOPN_PAIR_SORTED_SPACE:
        return True
    if space >= _TOPN_PAIR_STORAGE_SPACE:
        return False
    return None


def descending_orderby(table_node: Any) -> tuple[Any, bool] | None:
    """(key expression, descending) of the ORDERBY argument of a WINDOW / OFFSET call, or None when it has none."""
    orderby = next((a for a in table_node[2] if isinstance(a, tuple) and len(a) == 3 and a[0] == "call" and a[1] == "ORDERBY"), None)
    if orderby is None or not orderby[2]:
        return None
    return orderby[2][0], any(isinstance(a, tuple) and len(a) == 2 and a[0] == "table" and str(a[1]).upper() == "DESC" for a in orderby[2])


def window_walk_undecided(table_node: Any, row_count: int, key_is_numeric: bool) -> bool:
    """True when an iterator walks a WINDOW / OFFSET over ORDERBY(column, DESC) in a shape whose row order is not measured.

    Task 68 (live Power BI, order audit 3 grid): a relative WINDOW (REL bounds) over DESC comes back in no order the ORDERBY explains
    (Quantity 0..5: 1,0,2,3,4,5; Note: Late,,Paid), so it is refused. No one rule fits the eleven DESC WINDOW / OFFSET rows of that grid
    (walking the current rows upward and listing each window in ORDERBY order fits every WINDOW row, but the OFFSET rows over text need the
    opposite walk), so the shape stays refused instead of answered from a fit. OFFSET over DESC of a numeric column walks ascending (0,1,2,3,4;
    the window of Sales: -1.5, blank, 0, 2.5, 10.5), while the same OFFSET over text keeps the DESC order (Late, blank), so only the
    numeric two-row-or-more case is refused. ASC windows and ABS windows keep the ORDERBY order that was measured before."""
    if not (isinstance(table_node, tuple) and len(table_node) == 3 and table_node[0] == "call" and table_node[1] in {"WINDOW", "OFFSET"}):
        return False
    ordering = descending_orderby(table_node)
    if ordering is None or not ordering[1]:
        return False
    if table_node[1] == "WINDOW":
        # a window is fixed by its bounds alone only when both are ABS; a bound written without a type is REL
        return sum(1 for a in table_node[2] if isinstance(a, tuple) and len(a) == 2 and a[0] == "table" and str(a[1]).upper() == "ABS") < 2
    return key_is_numeric and row_count > 1


class AmbiguousTieOrder(Exception):
    """Two readings of the measured heap give a different row order and no live answer separates them."""


def heap_top(count: int, items: Sequence[Any], better: Callable[[Any, Any], bool]) -> list[Any]:
    """The rows Power BI's TOPN keeps, as the array of the binary heap it builds (worst kept item at the root).

    `better(a, b)` is True when a should replace b. Items arrive in walk order; the first `count` fill the heap by
    sift-up. An item that ties with the root (the worst kept) is pushed onto the heap too, so the heap grows. A better
    item takes the root's place and sifts down; when the root has tied rows and the rows strictly better than them number
    count - 1, the rest of the tied group is then popped from the root (last element to the root, sift down);
    otherwise the item is pushed and the tied group stays. The array order, not a sorted order, is what the rows
    are returned in (measured: TOPN(3, Quantity 0..5) walks out as 3,5,4; with ties 137 live Power BI orders over three walk orders, ASC/DESC and two keys fit exactly)."""
    heap: list[Any] = []
    pushed_ties: list[Any] = []  # rows that tied with the root of a full heap and were pushed since

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

    def pop_root() -> None:
        last = heap.pop()
        if heap:
            heap[0] = last
            sift_down(0)

    def root_group_size() -> int:
        """Rows tied with the root: they hang from the root, so walk down only through tied children."""
        size, stack = 0, [0]
        while stack:
            index = stack.pop()
            size += 1
            for child in (2 * index + 1, 2 * index + 2):
                if child < len(heap) and not better(heap[0], heap[child]) and not better(heap[child], heap[0]):
                    stack.append(child)
        return size

    for item in items:
        if len(heap) < count:
            heap.append(item)
            sift_up(len(heap) - 1)
        elif better(item, heap[0]):
            group = root_group_size()
            if len(heap) - group != count - 1:
                heap.append(item)  # the tied group still holds a place inside the top count: it stays
                sift_up(len(heap) - 1)
            else:
                if group == 2 and len(pushed_ties) == 1 and pushed_ties[0] in heap:
                    # a lone root and one tie pushed onto the full heap, evicted together: the array comes out one way
                    # when the tie is popped after the sift (most live Power BI answers) and another when it is taken
                    # out first (one live answer); where the two readings differ the order is not decided here
                    reference = list(heap)
                    heap[0] = item
                    sift_down(0)
                    for _ in range(group - 1):
                        pop_root()
                    first_reading = list(heap)
                    heap[:] = reference
                    for row in pushed_ties:
                        if row in heap:
                            position = heap.index(row)
                            last = heap.pop()
                            if position < len(heap):
                                heap[position] = last
                                sift_down(position)
                                sift_up(position)
                    heap[0] = item
                    sift_down(0)
                    if first_reading != heap:
                        raise AmbiguousTieOrder
                    heap[:] = first_reading
                else:
                    heap[0] = item  # the item takes the root's place and sifts down; the rest of the tied group is then popped
                    sift_down(0)
                    for _ in range(group - 1):
                        pop_root()
                pushed_ties.clear()
        elif not better(heap[0], item):  # ties with the worst kept row
            heap.append(item)
            if len(heap) > count:
                pushed_ties.append(item)
            sift_up(len(heap) - 1)
    return heap
