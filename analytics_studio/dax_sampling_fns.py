"""Task 91 (iteration 180): five DAX functions the local engine answers as Power BI does, or refuses.

Measured Power BI answers (live guest, 2026-11-08, model Facts) are raised with Power BI's exact message.
Argument-count and structural errors are raised in the parser (``check_syntax``); value errors and the
table evaluation of SAMPLECARTESIANPOINTSBYCOVER run at evaluation time. Anything not measured is refused with
``dax_typed.refusal``. A sampled subset is never returned: when MaxPoints is below the row count the answer is a refusal.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from . import dax_typed

NAMES = frozenset({"EXTERNALMEASURE", "NATURALJOINUSAGE", "SAMPLEAXISWITHLOCALMINMAX", "SAMPLECARTESIANPOINTSBYCOVER", "SELECTEDMEASUREFORMATSTRING"})
ARITY: dict[str, tuple[int, int | None]] = {
    "EXTERNALMEASURE": (1, 3), "NATURALJOINUSAGE": (1, 1), "SAMPLEAXISWITHLOCALMINMAX": (5, None),
    "SAMPLECARTESIANPOINTSBYCOVER": (4, 7), "SELECTEDMEASUREFORMATSTRING": (0, 0),
}
# Evaluated by evaluate_lookup_function (added to its arity table in measures.py).
LOOKUP_ARITY: dict[str, tuple[int, int | None]] = {"SELECTEDMEASUREFORMATSTRING": (0, 0)}
# Table functions (arity as SAMPLE); the table argument position is listed in TABLE_ARGUMENT.
TABLE_ARITY: dict[str, tuple[int, int | None]] = {
    "SAMPLECARTESIANPOINTSBYCOVER": (4, 7), "SAMPLEAXISWITHLOCALMINMAX": (5, None), "NATURALJOINUSAGE": (1, 1),
}
TABLE_ARGUMENT: dict[str, int] = {"SAMPLECARTESIANPOINTSBYCOVER": 1, "SAMPLEAXISWITHLOCALMINMAX": 1, "NATURALJOINUSAGE": 0}

EXTERNAL_MEASURE = "Failed to resolve name 'EXTERNALMEASURE'. It is not a valid table, variable, or function name."
NATURAL_JOIN_USAGE = "'NATURALJOINUSAGE' function can only be used as a value filter of SUMMARIZECOLUMNS."
SELECTED_FORMAT_MISUSED = "SELECTEDMEASUREFORMATSTRING misused. There is no measure reference in the current context."
CARTESIAN_POSITIVE = "The SampleCartesianPointsByCover function expects a positive numeric parameter value to be specified for argument 1."
CARTESIAN_COORDINATE = "The SampleCartesianPointsByCover function requires coordinate parameter (at argument number {position}) to be a numeric scalar expression."
CARTESIAN_RADIUS = "The SampleCartesianPointsByCover function requires radius parameter (at argument number 5) to be a numeric scalar expression."
CARTESIAN_MAX_MIN = "The SampleCartesianPointsByCover function expects MaxMinRatio as argument 6, since you specified a radius column."
CARTESIAN_MAX_BLANK = "The SampleCartesianPointsByCover function expects MaxBlankRatio as argument 7, since you specified a radius column."
AXIS_RESOLUTION = "The SampleAxisWithLocalMinMax function requires a Minimum-Resolution parameter to be specified at argument number {position}."
AXIS_MEASURE = "The SampleAxisWithLocalMinMax function requires Measure parameter (at argument number 6) to be a numeric column reference from the specified table."


def _errors() -> tuple[type, type]:
    from .measures import MeasureError, _HardError  # imported late: measures imports this module

    return MeasureError, _HardError


def check_syntax(function: str, arguments: tuple[tuple[Any, ...], ...]) -> None:
    """Parse-time checks: argument counts and the measured structural errors; any other shape is refused."""
    measure_error, _ = _errors()
    low, high = ARITY[function]
    if len(arguments) < low:
        raise measure_error(f"Too few arguments were passed to the {function} function. The minimum argument count for the function is {low}.")
    if high is not None and len(arguments) > high:
        raise measure_error(f"Too many arguments were passed to the {function} function. The maximum argument count for the function is {high}.")
    if any(argument[0] == "omitted" for argument in arguments):
        raise dax_typed.refusal(f"A {function} call with an omitted argument is not modelled by the local engine.")
    if function == "EXTERNALMEASURE":
        raise measure_error(EXTERNAL_MEASURE)
    if function == "NATURALJOINUSAGE":
        raise measure_error(NATURAL_JOIN_USAGE)
    if function == "SAMPLECARTESIANPOINTSBYCOVER":
        if len(arguments) == 5:
            raise measure_error(CARTESIAN_MAX_MIN)
        if len(arguments) == 6:
            raise measure_error(CARTESIAN_MAX_BLANK)
        return
    if function == "SAMPLEAXISWITHLOCALMINMAX":
        if len(arguments) == 5:
            raise measure_error(AXIS_RESOLUTION.format(position=6))
        if len(arguments) in {6, 7} and arguments[5][0] != "reference":
            raise measure_error(AXIS_MEASURE)
        raise dax_typed.refusal("SAMPLEAXISWITHLOCALMINMAX is not modelled by the local engine (no successful call measured).")
    # SELECTEDMEASUREFORMATSTRING is a runtime error (IF(FALSE(), ...) is fine): checked at evaluation.


def is_table_argument(parent_function: str, argument_index: int) -> bool:
    """Whether an argument slot of one of these table functions takes a table expression."""
    return TABLE_ARGUMENT.get(parent_function) == argument_index


def selected_measure_format_string() -> str:
    """SELECTEDMEASUREFORMATSTRING(): no calculation groups exist locally, so there is never a measure reference."""
    measure_error, _ = _errors()
    raise measure_error(SELECTED_FORMAT_MISUSED)


def _max_points(value: Any) -> int:
    """MaxPoints as a positive whole number: text converts (Integer), BLANK and zero or negative values are errors."""
    measure_error, _ = _errors()
    if isinstance(value, bool):
        raise dax_typed.refusal("SAMPLECARTESIANPOINTSBYCOVER with a Boolean MaxPoints is not modelled by the local engine.")
    if isinstance(value, str):
        try:
            number = Decimal(dax_typed.text_to_number(value))
        except measure_error as error:
            raise measure_error(f"Cannot convert value '{value}' of type Text to type Integer.") from error
    elif value is None:
        number = Decimal(0)
    elif isinstance(value, (int, Decimal)):
        number = Decimal(value)
    else:
        raise dax_typed.refusal("SAMPLECARTESIANPOINTSBYCOVER with a non-numeric MaxPoints is not modelled by the local engine.")
    if not number.is_finite():
        raise dax_typed.refusal("SAMPLECARTESIANPOINTSBYCOVER with a non-finite MaxPoints is not modelled by the local engine.")
    if number <= 0:
        raise measure_error(CARTESIAN_POSITIVE)
    if number != number.to_integral_value():
        raise dax_typed.refusal("SAMPLECARTESIANPOINTSBYCOVER with a fractional MaxPoints (rounding) is not modelled by the local engine.")
    return int(number)


def cartesian_points(
    arguments: tuple[tuple[Any, ...], ...],
    table_rows_of: Callable[[tuple[Any, ...]], tuple[dict[str, Any], list[dict[str, Any]]]],
    scalar: Callable[[tuple[Any, ...], tuple[dict[str, Any], dict[str, Any], int] | None], Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """SAMPLECARTESIANPOINTSBYCOVER: the table's rows when MaxPoints covers them all; a smaller sample is refused."""
    measure_error, _ = _errors()
    max_points = _max_points(scalar(arguments[0], None))
    context, rows = table_rows_of(arguments[1])
    if rows:
        # coordinate arguments 3 and 4, and the radius (argument 5 of the 7-argument form), must be numeric in every row
        for position in (2, 3, 4) if len(arguments) == 7 else (2, 3):
            for index, row in enumerate(rows):
                try:
                    value = scalar(arguments[position], (context, row, index))
                except measure_error as error:
                    if "non-numeric value" not in str(error):  # a text column read as a number: Power BI's own wording
                        raise
                    raise measure_error(CARTESIAN_RADIUS if position == 4 else CARTESIAN_COORDINATE.format(position=position + 1)) from error
                if value is None or (isinstance(value, (int, Decimal)) and not isinstance(value, bool)):
                    continue
                if isinstance(value, str):
                    raise measure_error(CARTESIAN_RADIUS if position == 4 else CARTESIAN_COORDINATE.format(position=position + 1))
                raise dax_typed.refusal("SAMPLECARTESIANPOINTSBYCOVER with a non-numeric coordinate or radius is not modelled by the local engine.")
    if max_points >= len(rows):
        return context, list(rows)
    raise dax_typed.refusal("SAMPLECARTESIANPOINTSBYCOVER that drops rows (MaxPoints below the row count) is not modelled by the local engine.")


def table_rows(
    function: str,
    arguments: tuple[tuple[Any, ...], ...],
    table_rows_of: Callable[[tuple[Any, ...]], tuple[dict[str, Any], list[dict[str, Any]]]],
    scalar: Callable[[tuple[Any, ...], tuple[dict[str, Any], dict[str, Any], int] | None], Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if function == "SAMPLECARTESIANPOINTSBYCOVER":
        return cartesian_points(arguments, table_rows_of, scalar)
    raise dax_typed.refusal(f"{function} is not modelled by the local engine.")
