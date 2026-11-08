"""Task 94 (iteration 183): the 14 visual-calculation functions, outside a visual calculation.

Power BI only evaluates these functions inside a visual calculation (a later feature of the report visuals). Outside
one, every call is an error, raised at parse time with Power BI's exact message (measured live, 2026-11-08, 210 cases):
argument count first, then LOOKUPWITHTOTALS' column-reference rule, then the "can only be used" message.
Nothing is evaluated: ``check_syntax`` always raises (or refuses), so no value is ever produced.
"""
from __future__ import annotations

from typing import Any

from . import dax_typed

NAMES = frozenset({
    "RUNNINGSUM", "MOVINGAVERAGE", "FIRST", "LAST", "NEXT", "PREVIOUS", "RANGE", "LOOKUP",
    "LOOKUPWITHTOTALS", "EXPAND", "EXPANDALL", "COLLAPSE", "COLLAPSEALL", "ISATLEVEL",
})
# (minimum, maximum) argument counts; None means no maximum.
ARITY: dict[str, tuple[int, int | None]] = {
    "RUNNINGSUM": (1, 5), "MOVINGAVERAGE": (2, 7), "FIRST": (1, 5), "LAST": (1, 5), "NEXT": (1, 6),
    "PREVIOUS": (1, 6), "RANGE": (1, 6), "LOOKUP": (1, None), "LOOKUPWITHTOTALS": (1, None),
    "EXPAND": (1, None), "EXPANDALL": (1, 2), "COLLAPSE": (1, None), "COLLAPSEALL": (1, 2), "ISATLEVEL": (1, 1),
}

# Measured quirk (live Power BI, 2026-11-08): FIRST names LAST in its visual-calculation message; every other name is its own.
VISUAL_ONLY_NAME: dict[str, str] = {"FIRST": "LAST"}

LOOKUP_COLUMN = "Function LOOKUPWITHTOTALS expects a column reference as argument number 2."


def _errors() -> type:
    from .measures import MeasureError  # imported late: measures imports this module

    return MeasureError


def check_syntax(function: str, arguments: tuple[tuple[Any, ...], ...]) -> None:
    """Parse-time checks for a visual-calculation name written as a call: arity, then the argument kind, then refusal."""
    measure_error = _errors()
    low, high = ARITY[function]
    if len(arguments) < low:
        raise measure_error(f"Too few arguments were passed to the {function} function. The minimum argument count for the function is {low}.")
    if high is not None and len(arguments) > high:
        raise measure_error(f"Too many arguments were passed to the {function} function. The maximum argument count for the function is {high}.")
    if any(argument[0] == "omitted" for argument in arguments):
        raise dax_typed.refusal(f"A {function} call with an omitted argument is not modelled by the local engine.")
    if function == "LOOKUPWITHTOTALS" and len(arguments) >= 2 and arguments[1][0] != "reference":
        raise measure_error(LOOKUP_COLUMN)
    raise measure_error(f"{VISUAL_ONLY_NAME.get(function, function)} can only be used in the expression of a visual calculation.")
