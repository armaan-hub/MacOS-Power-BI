"""A CALCULATETABLE (or RELATEDTABLE) inside the scalar side of a Boolean CALCULATE filter (iteration 86).

`CALCULATE(x, Facts[Quantity] > COUNTROWS(CALCULATETABLE(Facts, Facts[Region] = "East")))` is FILTER(ALL(Facts[Quantity]), ...) in DAX, so the
CALCULATETABLE could read the row of that hidden iteration (a context transition).  Live Power BI Desktop does one of two things with each such
scalar, and the saved batteries in tools/parity (sdet_filters, critic_shapes, boolean_scalar_rhs, round2, round3) show which:

* HOIST: the scalar is evaluated once, in the context CALCULATE is written in, and is a constant of the filter (no transition).
* TRANSITION: the filter really is FILTER(ALL(columns), test): every distinct value of the filtered columns is a row context and the
  CALCULATETABLE sees it (`Quantity < COUNTROWS(CALCULATETABLE(Facts))` is 1 on the six-row Facts table, not 6).

The rule, from 332 saved Power BI answers (155 answered before by the older hoist rule, 177 refused until now) and about 12,500 fresh probes on the
Facts table and on the ZO and ZB relationship models (a sample is frozen in tests/fixtures_iter86_fresh.json), for a filter written at the top level
of a measure (no iterator row context, no filter from an outer CALCULATE), reading one table:

* a scalar that is an X-iterator (SUMX, MAXX, AVERAGEX, MINX, COUNTX, ...) over a CALCULATETABLE or a CALCULATE: HOIST, whatever its filters are;
* a scalar COUNTROWS(CALCULATETABLE(..)) (also COUNTROWS(DISTINCT(CALCULATETABLE(..))) and COUNTROWS(RELATEDTABLE(t)), which is CALCULATETABLE(t)):
  - no filter argument of the CALCULATETABLE is a Boolean test or NOT(..) (none at all, or ALL, REMOVEFILTERS, ALLEXCEPT): TRANSITION;
  - otherwise it depends on what the whole filter reads first: a column (`Quantity > COUNTROWS(..)`, `Quantity + COUNTROWS(..) > 5`,
    `Region <> "N" && COUNTROWS(..) < Quantity`): HOIST; the scalar (`COUNTROWS(..) < Quantity`, `COUNTROWS(..) + Quantity > 5`): TRANSITION;
* a filter whose scalars would need different readings (one hoists, another transitions) is refused: a fresh probe disagreed with the
  per-scalar reading.

Everything else stays refused, Power BI's answer for it was not established: a CALCULATETABLE inside a CALCULATETABLE (the outer filters reach the
inner one differently), ALLSELECTED among the filters (it restores the iterated column), KEEPFILTERS among the filters (on the models with repeated
quantities Power BI sometimes held the filtered column of the KEEPFILTERS in the row context as well, sometimes not), FILTER(..) among the filters,
a function around the scalar that the older right-hand-side hoist does not know, a filter inside an iterator or under an outer CALCULATE's
filters, and a filter that reads a second table.  A scalar holding two transitions next to a column (an X-iterator over CALCULATE(CALCULATE(..))) used
to be answered per row by the older path, wrongly in 6 of 6 fresh probes; it is refused now.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, NamedTuple

HOIST = "hoist"
TRANSITION = "transition"

X_ITERATORS = frozenset({
    "SUMX", "AVERAGEX", "MAXX", "MINX", "COUNTX", "COUNTAX", "CONCATENATEX", "PRODUCTX", "MEDIANX", "GEOMEANX",
    "PERCENTILEX.INC", "PERCENTILEX.EXC", "STDEVX.S", "STDEVX.P", "VARX.S", "VARX.P",
})
_BOOLEAN_TESTS = frozenset({"comparison", "logical"})
_BOOLEAN_FILTER_CALLS = frozenset({"NOT"})  # a Boolean test among the CALCULATETABLE filters (FILTER(..) there is not planned: one answer only)
_PLAIN_MODIFIERS = frozenset({"ALL", "REMOVEFILTERS", "ALLEXCEPT"})  # not ALLSELECTED: it restores the row's own column
_WRAPPERS = frozenset({"KEEPFILTERS", "NOT"})
_COMBINERS = frozenset({"AND", "OR"})


_TRANSITION_CALLS = frozenset({"CALCULATE", "CALCULATETABLE"})


def has_calculatetable(node: Any) -> bool:
    """A CALCULATETABLE or CALCULATE (a context transition) anywhere inside."""
    if not isinstance(node, tuple) or not node:
        return False
    if node[0] == "call" and node[1] in _TRANSITION_CALLS:
        return True
    return any(has_calculatetable(child) for child in node if isinstance(child, tuple))


def _calculatetables(node: Any, found: list[tuple[Any, ...]]) -> None:
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "call" and node[1] in _TRANSITION_CALLS:
        found.append(node)
    for child in node:
        if isinstance(child, tuple):
            _calculatetables(child, found)


def _filter_kind(argument: tuple[Any, ...]) -> str | None:
    """"test" for a Boolean test / NOT(..), "plain" for a modifier that only removes or keeps filters, None for anything else."""
    if argument[0] in _BOOLEAN_TESTS:
        return "test"
    if argument[0] == "call":
        if argument[1] in _BOOLEAN_FILTER_CALLS:
            return "test"
        if argument[1] in _PLAIN_MODIFIERS:
            return "plain"
        if argument[1] == "KEEPFILTERS" and len(argument[2]) == 1:
            inner = argument[2][0]
            if inner[0] in _BOOLEAN_TESTS or (inner[0] == "call" and inner[1] in _BOOLEAN_FILTER_CALLS):
                return "keep"  # iteration 88: a KEEPFILTERS(test) does not hoist (it intersects the row's own filter) but its columns are still picked
    return None  # KEEPFILTERS of anything but a Boolean test, FILTER(..), ALLSELECTED ...: not established


X_KIND = "x-iterator"
COUNT_KIND = "count"


def _scalar_mode(scalar: tuple[Any, ...], scalar_first: bool) -> tuple[str, bool, str] | None:
    """(mode, whether the position of the scalar in the comparison decided it, the kind of the scalar)."""
    inside: list[tuple[Any, ...]] = []
    _calculatetables(scalar, inside)
    if len(inside) != 1:
        return None
    if scalar[0] == "call" and scalar[1] in X_ITERATORS:
        return HOIST, False, X_KIND
    if not (scalar[0] == "call" and scalar[1] == "COUNTROWS" and len(scalar[2]) == 1):
        return None
    table = scalar[2][0]
    if table[0] == "table_call" and table[1] == "DISTINCT" and isinstance(table[2], tuple) and table[2] and table[2][0] == "call":
        table = table[2]  # COUNTROWS(DISTINCT(CALCULATETABLE(..)))
    if not (table[0] == "call" and table[1] == "CALCULATETABLE"):
        return None
    tables: list[tuple[Any, ...]] = []
    _calculatetables(table, tables)
    if len(tables) != 1:
        return None  # a CALCULATETABLE inside a CALCULATETABLE: its outer filters reach the inner one in a way that was not established
    kinds = []
    for calculatetable in tables:
        for argument in calculatetable[2][1:]:
            kind = _filter_kind(argument)
            if kind is None:
                return None
            kinds.append(kind)
    if "test" not in kinds:
        return TRANSITION, False, COUNT_KIND
    return (TRANSITION if scalar_first else HOIST), True, COUNT_KIND


def _leaves(node: Any, direct_columns: Callable[[Any], Iterable[Any]], out: list[tuple[str, tuple[Any, ...]]]) -> None:
    """The columns and the CALCULATETABLE-carrying scalars of an expression, in the order they are read (left to right)."""
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "reference":
        out.append(("column", node))
        return
    if node[0] == "call" and has_calculatetable(node) and not any(True for _ in direct_columns(node)):
        out.append(("scalar", node))
        return
    for child in (node if isinstance(node[0], tuple) else node[1:]):
        if isinstance(child, tuple):
            _leaves(child, direct_columns, out)


def _is_boolean_test(argument: tuple[Any, ...]) -> bool:
    """A Boolean filter (a comparison, && / ||, AND, OR, NOT, under KEEPFILTERS), not a table filter such as FILTER(..) or TOPN(..)."""
    core = core_of(argument)
    return core[0] in _BOOLEAN_TESTS or (core[0] == "call" and (core[1] in _COMBINERS or core[1] == "NOT"))


def has_nested_transition_scalar(argument: tuple[Any, ...], direct_columns: Callable[[Any], Iterable[Any]]) -> bool:
    """Whether a scalar of the filter (no column of its own) holds two context transitions, CALCULATE(CALCULATE(..)) and the like."""
    if not _is_boolean_test(argument):
        return False
    leaves: list[tuple[str, tuple[Any, ...]]] = []
    _leaves(argument, direct_columns, leaves)
    if not any(kind == "column" for kind, _node in leaves):
        return False
    for kind, node in leaves:
        if kind == "scalar":
            inside: list[tuple[Any, ...]] = []
            _calculatetables(node, inside)
            if len(inside) >= 2:
                return True
    return False


def _comparisons(node: Any, out: list[tuple[Any, ...]]) -> None:
    if not isinstance(node, tuple) or not node:
        return
    if node[0] == "comparison":
        out.append(node)
        return
    for child in node:
        if isinstance(child, tuple):
            _comparisons(child, out)


def core_of(argument: tuple[Any, ...]) -> tuple[Any, ...]:
    """The Boolean test under KEEPFILTERS(..) wrappers (NOT stays part of the test)."""
    while argument[0] == "call" and argument[1] == "KEEPFILTERS" and len(argument[2]) == 1:
        argument = argument[2][0]
    return argument


class Plan(NamedTuple):
    mode: str  # HOIST: every scalar is a constant of the filter; TRANSITION: FILTER(ALL(columns), test) with the `hoisted` scalars as constants
    hoisted: list[tuple[Any, ...]]  # scalar nodes to evaluate once, in the context the filter is written in
    columns: list[tuple[Any, ...]]  # distinct column references of the filter, in the order they are read
    counted: bool = False  # HOIST of the one COUNTROWS(CALCULATETABLE(..)) scalar of the filter (iteration 88): read with the filter's columns cleared
    scalars: int = 1  # how many CALCULATETABLE-carrying scalars the filter has
    extra_columns: tuple[tuple[Any, ...], ...] = ()  # columns the hoisted COUNTROWS(CALCULATETABLE(..)) scalars filter by, the filter replaces them too


def test_columns(scalar: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    """The column references in the Boolean tests among the filters of the CALCULATETABLE of a COUNTROWS(CALCULATETABLE(..)) scalar."""
    found: list[tuple[Any, ...]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, tuple) or not node:
            return
        if node[0] == "reference":
            if not any(node[1:] == other[1:] for other in found):
                found.append(node)
            return
        for child in node:
            if isinstance(child, tuple):
                walk(child)

    tables: list[tuple[Any, ...]] = []
    _calculatetables(scalar, tables)
    for calculatetable in tables:
        for argument in calculatetable[2][1:]:
            if _filter_kind(argument) in {"test", "keep"}:
                walk(argument)
    return found


def plan(argument: tuple[Any, ...], direct_columns: Callable[[Any], Iterable[Any]]) -> Plan | None:
    """How Power BI treats one Boolean filter argument of a top-level CALCULATE that has a CALCULATETABLE in it.

    None when the shape is not one whose Power BI answer was established."""
    if not _is_boolean_test(argument) or not has_calculatetable(argument):
        return None
    leaves: list[tuple[str, tuple[Any, ...]]] = []
    _leaves(argument, direct_columns, leaves)
    scalars = [node for kind, node in leaves if kind == "scalar"]
    columns = [node for kind, node in leaves if kind == "column"]
    if not scalars or not columns:
        return None
    covered: list[tuple[Any, ...]] = []
    for scalar in scalars:
        _calculatetables(scalar, covered)
    everything: list[tuple[Any, ...]] = []
    _calculatetables(argument, everything)
    if len(covered) != len(everything):
        return None  # a CALCULATETABLE outside a scalar the rule describes (IN CALCULATETABLE(..), a bare table operand)
    # what the whole filter reads first decides, not the comparison the scalar sits in (fresh probes: Region <> "North" && COUNTROWS(..) - Quantity < 3)
    scalar_first = leaves[0][0] == "scalar"
    hoisted: list[tuple[Any, ...]] = []
    kinds: set[str] = set()
    transitions = 0
    for scalar in scalars:
        decided = _scalar_mode(scalar, scalar_first)
        if decided is None:
            return None
        mode, by_position, kind = decided
        if by_position and scalar_first:
            # the position rule is established when the filter starts with the scalar, or when it starts with a column; with several
            # comparisons it was only seen starting with a column
            comparisons: list[tuple[Any, ...]] = []
            _comparisons(argument, comparisons)
            if len(comparisons) > 1:
                return None
        if mode == HOIST:
            hoisted.append(scalar)
            kinds.add(kind)
        else:
            transitions += 1
    if hoisted and transitions:
        return None  # one scalar hoists and another transitions: a fresh probe (ABS(Quantity) = COUNTROWS(.. ALL(Quantity)) + COUNTROWS(.. NOT(Region = "East"))) disagreed
    if len(kinds) > 1:
        return None  # an X-iterator and a COUNTROWS(CALCULATETABLE(..)) in one hoisted filter: read differently, not probed together
    distinct: list[tuple[Any, ...]] = []
    for reference in columns:
        if not any(reference[1:] == other[1:] for other in distinct):
            distinct.append(reference)
    if len(scalars) > 1 and any(_has_keepfilters(scalar) for scalar in scalars):
        return None  # KEEPFILTERS(test) beside another scalar: only probed alone
    if hoisted and kinds == {COUNT_KIND} and len(scalars) == 1:
        extra: list[tuple[Any, ...]] = []
        for scalar in hoisted:
            for reference in test_columns(scalar):
                if not any(reference[1:] == other[1:] for other in distinct + extra):
                    extra.append(reference)
        return Plan(HOIST, hoisted, distinct, counted=True, extra_columns=tuple(extra))
    if transitions and len(scalars) == 1 and not scalar_first and _is_count_scalar(scalars[0]):
        # a transition read with the column first (only KEEPFILTERS(test)s among the filters, or none): the filter is FILTER(ALL(Q, the columns
        # of those tests), ..); with the scalar first only the filtered column is iterated (live probes, iteration 88)
        extra = []
        for reference in test_columns(scalars[0]):
            if not any(reference[1:] == other[1:] for other in distinct + extra):
                extra.append(reference)
        return Plan(TRANSITION, hoisted, distinct, scalars=1, extra_columns=tuple(extra))
    return Plan(HOIST if not transitions else TRANSITION, hoisted, distinct, scalars=len(scalars))


def _is_count_scalar(scalar: tuple[Any, ...]) -> bool:
    return scalar[0] == "call" and scalar[1] == "COUNTROWS"


def _has_keepfilters(scalar: tuple[Any, ...]) -> bool:
    tables: list[tuple[Any, ...]] = []
    _calculatetables(scalar, tables)
    return any(_filter_kind(argument) == "keep" for calculatetable in tables for argument in calculatetable[2][1:])
