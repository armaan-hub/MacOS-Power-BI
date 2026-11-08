"""Task 58 (iteration 148): ten DAX functions the local engine answers as Power BI does, or refuses.

The measured Power BI answers (live, 2026-11-05, guest model: one table Facts, no date column, import mode) are raised
with Power BI's exact message. Compile-time checks run in the parser (``check_syntax``); the model-dependent ones run at
evaluation time (CALENDARAUTO, PATH) and USEROBJECTID reads the Windows process user. Anything the plan does not measure
is refused with ``dax_typed.refusal``. Nothing here reads tools/parity, fixtures or scratchpad files.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Iterable

from . import dax_dates, dax_typed
from .calendar_tables import CalendarTableError, generate_calendar_auto
from .file_import import ImportCandidate

STORAGE_MODE = "The function APPROXIMATEDISTINCTCOUNT isn't supported for this storage mode."
NO_SELECTED_MEASURE = "There is no measure reference in the current context to be applied as SELECTEDMEASURE."
NO_SELECTED_MEASURE_NAME = "There is no measure reference in the current context that can be used by SELECTEDMEASURENAME."
BAD_ISSELECTED = "Invalid input arguments for ISSELECTEDMEASURE."
DATESWTD_PARAMETER = "DATESWTD's parameter 1 must be a calendar reference."
TOTALWTD_PARAMETER = "TOTALWTD's parameter 2 must be a calendar reference."
DETAILROWS_MEASURE = "The input parameter for the DETAILROWS function is not a valid measure reference."
CALENDARAUTO_MISSING = "CALENDARAUTO function can not find a base column of DateTime type in the model."
KEYWORD_LAST = "The last argument must be one of these keywords: DAY, MONTH, QUARTER, or YEAR."
PATH_TYPES = (
    "The columns specified in the PATH function must be from the same table, have the same data type and that type must be Integer or Text."
)

# Task 93 (iteration 182): the six week functions; every answer is an error (no calendar objects in the guest model)
WEEK_CALENDAR = frozenset({"STARTOFWEEK", "ENDOFWEEK", "NEXTWEEK", "PREVIOUSWEEK"})
WEEK_KEYWORD = frozenset({"OPENINGBALANCEWEEK", "CLOSINGBALANCEWEEK"})
WEEK_NAMES = WEEK_CALENDAR | WEEK_KEYWORD

NAMES = frozenset({
    "APPROXIMATEDISTINCTCOUNT", "CALENDARAUTO", "DATESWTD", "TOTALWTD", "DETAILROWS", "PATH",
    "SELECTEDMEASURE", "SELECTEDMEASURENAME", "ISSELECTEDMEASURE", "USEROBJECTID",
}) | WEEK_NAMES
ARITY: dict[str, tuple[int, int | None]] = {
    "APPROXIMATEDISTINCTCOUNT": (1, 1), "CALENDARAUTO": (0, 1), "DATESWTD": (1, 2), "TOTALWTD": (2, 4),
    "DETAILROWS": (1, 1), "PATH": (2, 2), "SELECTEDMEASURE": (0, 0), "SELECTEDMEASURENAME": (0, 0),
    "ISSELECTEDMEASURE": (1, None), "USEROBJECTID": (0, 0),
    "STARTOFWEEK": (1, 1), "ENDOFWEEK": (1, 1), "NEXTWEEK": (1, 1), "PREVIOUSWEEK": (1, 1),
    "OPENINGBALANCEWEEK": (2, 3), "CLOSINGBALANCEWEEK": (2, 3),
}
# Evaluated by evaluate_lookup_function (added to its arity table in measures.py).
LOOKUP_ARITY: dict[str, tuple[int, int | None]] = {"PATH": (2, 2), "USEROBJECTID": (0, 0)}
# Table functions of the model (arity as CALENDAR).
TABLE_ARITY: dict[str, tuple[int, int | None]] = {"CALENDARAUTO": (0, 1)}
# Static result categories the iterator and comparison checks read (both are text).
RESULT_CATEGORY = {"PATH": "text", "USEROBJECTID": "text"}
_DATE_TYPES = {"date", "datetime"}
_NON_MEASURE_NODES = {"number", "string", "boolean", "blank", "call"}


def _errors() -> tuple[type, type]:
    from .measures import MeasureError, _HardError  # imported late: measures imports this module

    # live Power BI: the model and PATH argument errors fail the whole query, IFERROR / ISERROR cannot catch them
    return MeasureError, _HardError


def check_syntax(function: str, arguments: tuple[tuple[Any, ...], ...]) -> None:
    """Parse-time checks: the measured argument errors; any other shape of these functions is refused."""
    measure_error, _ = _errors()
    if function in WEEK_NAMES:
        _check_week(function, arguments)
        return
    low, high = ARITY[function]
    if len(arguments) < low or (high is not None and len(arguments) > high) or any(argument[0] == "omitted" for argument in arguments):
        raise dax_typed.refusal(f"A {function} call with this number of arguments is not modelled by the local engine.")
    if function == "APPROXIMATEDISTINCTCOUNT":
        raise measure_error(STORAGE_MODE)
    if function == "SELECTEDMEASURE":
        raise measure_error(NO_SELECTED_MEASURE)
    if function == "SELECTEDMEASURENAME":
        raise measure_error(NO_SELECTED_MEASURE_NAME)
    if function == "ISSELECTEDMEASURE":
        if arguments[0][0] == "number":
            raise measure_error(BAD_ISSELECTED)
        raise dax_typed.refusal("ISSELECTEDMEASURE with a measure reference is not modelled by the local engine (no calculation groups).")
    if function == "DATESWTD":
        raise measure_error(DATESWTD_PARAMETER)
    if function == "TOTALWTD":
        raise measure_error(TOTALWTD_PARAMETER)
    if function == "DETAILROWS":
        if arguments[0][0] in _NON_MEASURE_NODES:
            raise measure_error(DETAILROWS_MEASURE)
        raise dax_typed.refusal("DETAILROWS of a measure reference is not modelled by the local engine (no detail-rows definitions).")
    if function == "PATH":
        for position, argument in enumerate(arguments, 1):
            if argument[0] == "reference" and argument[1] == "":
                raise measure_error(f"[{argument[2]}] is not a valid reference to a column in a table.")
            if argument[0] != "reference":
                raise measure_error(f"Function Path expects a column reference as argument number {position}.")
    # CALENDARAUTO and USEROBJECTID depend on the model or the environment: checked at evaluation.


def _check_week(function: str, arguments: tuple[tuple[Any, ...], ...]) -> None:
    """Task 93: Power BI's parse-time messages for the week functions (arity, then the argument kind)."""
    measure_error, _ = _errors()
    low, high = ARITY[function]
    if len(arguments) < low:
        raise measure_error(
            f"Too few arguments were passed to the {function} function. The minimum argument count for the function is {low}.")
    if high is not None and len(arguments) > high:
        raise measure_error(
            f"Too many arguments were passed to the {function} function. The maximum argument count for the function is {high}.")
    if any(argument[0] == "omitted" for argument in arguments):
        raise dax_typed.refusal(f"A {function} call with an omitted argument is not modelled by the local engine.")
    if function in WEEK_CALENDAR:
        raise measure_error(f"{function}'s parameter 1 must be a calendar reference.")
    raise measure_error(KEYWORD_LAST)


def date_columns(tables: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """The imported date and datetime columns of the loaded model (derived tables are not model columns)."""
    found: list[dict[str, str]] = []
    for table in tables:
        if table.get("derived"):
            continue
        headers = [str(header) for header in table.get("headers", [])]
        for column, column_type in dict(table.get("column_types", {})).items():
            kind = str(column_type).casefold()
            if kind in _DATE_TYPES and str(column) in headers:
                found.append({"source_id": str(table["id"]), "column": str(column), "type": kind})
    return found


def require_date_column(tables: Iterable[dict[str, Any]]) -> None:
    """Power BI's CALENDARAUTO error when the model has no DateTime column (measured on the guest)."""
    _, runtime_error = _errors()
    if not date_columns(list(tables)):
        raise runtime_error(CALENDARAUTO_MISSING)


def calendar_auto_rows(arguments: tuple[tuple[Any, ...], ...], tables: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """CALENDARAUTO([fiscal_year_end_month]) as Date rows: whole fiscal years around every model date (documented)."""
    tables = list(tables)
    require_date_column(tables)
    month = 12
    if arguments:
        if arguments[0][0] != "number":
            raise dax_typed.refusal("CALENDARAUTO over a model column is not modelled by the local engine.")
        value = arguments[0][1]
        if not isinstance(value, Decimal) or value != value.to_integral_value() or not 1 <= int(value) <= 12:
            raise dax_typed.refusal("CALENDARAUTO with a fiscal year end month outside 1 to 12 is not modelled by the local engine.")
        month = int(value)
    columns = date_columns(tables)
    wanted: dict[str, set[str]] = {}
    for definition in columns:
        wanted.setdefault(definition["source_id"], set()).add(definition["column"])
    candidates: dict[str, ImportCandidate] = {}
    for table in tables:
        if table.get("derived") or str(table["id"]) not in wanted:
            continue
        for row in table.get("rows", []):
            for column in wanted[str(table["id"])]:
                if row.get(column) is not None and not isinstance(row.get(column), str):
                    raise dax_typed.refusal("CALENDARAUTO over typed model dates is not modelled by the local engine.")
        candidates[str(table["id"])] = ImportCandidate(
            "query", [str(header) for header in table["headers"]], [dict(row) for row in table["rows"]], {}, [],
            source_id=str(table["id"]),
        )
    try:
        generated = generate_calendar_auto(candidates, columns, month)
    except CalendarTableError as error:
        raise dax_typed.refusal(f"CALENDARAUTO over these model dates is not modelled by the local engine ({error}).") from error
    return [{"Date": dax_dates.from_datetime(_iso_date(row["Date"]))} for row in generated.rows]


def _iso_date(text: str) -> date:
    return date.fromisoformat(text)


def _actual_column(context: dict[str, Any], column: str) -> str:
    for header in context["headers"]:
        if str(header).casefold() == column.casefold():
            return str(header)
    raise dax_typed.refusal(f"PATH over column {column!r} that the model table does not hold is not modelled by the local engine.")


def _column_type(context: dict[str, Any], actual: str) -> str:
    for column, column_type in dict(context.get("column_types", {})).items():
        if str(column).casefold() == actual.casefold():
            return str(column_type).casefold()
    return ""


def _key(value: Any) -> str | None:
    """A PATH id or parent as text (Integer or Text cells only); None is a blank cell."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise dax_typed.refusal("PATH over a non-Integer, non-Text cell is not modelled by the local engine.")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return str(int(value))
    raise dax_typed.refusal("PATH over a non-Integer, non-Text cell is not modelled by the local engine.")


def path_value(
    arguments: tuple[tuple[Any, ...], ...],
    row_context: tuple[dict[str, Any], dict[str, Any], int] | None,
    full_table: Callable[[str], dict[str, Any]],
    typed_row: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
) -> str:
    """PATH(id, parent): the ids from the root to the current row, joined by '|' (documented, not yet measured)."""
    _, runtime_error = _errors()
    (_, id_table, id_column), (_, parent_table, parent_column) = arguments
    id_context = full_table(id_table)
    parent_context = full_table(parent_table)
    if id_context.get("derived") or parent_context.get("derived"):
        raise dax_typed.refusal("PATH over a derived table is not modelled by the local engine.")
    if id_context["id"] != parent_context["id"] or id_column.casefold() == parent_column.casefold():
        raise runtime_error(PATH_TYPES)
    id_actual = _actual_column(id_context, id_column)
    parent_actual = _actual_column(parent_context, parent_column)
    id_type = _column_type(id_context, id_actual)
    if id_type != _column_type(parent_context, parent_actual) or id_type not in {"whole_number", "text"}:
        raise runtime_error(PATH_TYPES)
    if row_context is None:
        raise dax_typed.refusal("PATH outside a row context is not modelled by the local engine.")
    current_context, current_row, _ = row_context
    if current_context.get("derived") or current_context.get("id") != id_context["id"]:
        raise dax_typed.refusal("PATH from a row of another table is not modelled by the local engine.")
    parent_of: dict[str, str | None] = {}
    for row in id_context["rows"]:
        typed = typed_row(id_context, row)
        key = _key(typed.get(id_actual))
        if key is None or key in parent_of:
            raise dax_typed.refusal("PATH over blank or duplicate ids is not modelled by the local engine.")
        parent_of[key] = _key(typed.get(parent_actual))
    key = _key(typed_row(id_context, current_row).get(id_actual))
    chain: list[str] = []
    seen: set[str] = set()
    while True:
        if key is None or key not in parent_of:
            raise dax_typed.refusal("PATH from a row whose id is not in the table is not modelled by the local engine.")
        if key in seen:
            raise dax_typed.refusal("PATH over a parent loop is not modelled by the local engine.")
        seen.add(key)
        chain.append(key)
        parent = parent_of[key]
        if parent is None:
            break
        if parent not in parent_of:
            raise dax_typed.refusal("PATH over a missing parent is not modelled by the local engine.")
        key = parent
    return "|".join(reversed(chain))


_SID = re.compile(r'"(S-1-[0-9-]+)"\s*$')


def user_object_id() -> str:
    """USEROBJECTID(): the Windows SID of the process user. Off Windows it is refused (environment value)."""
    if sys.platform != "win32":
        raise dax_typed.refusal("USEROBJECTID is not modelled by the local engine off Windows.")
    try:
        output = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise dax_typed.refusal("USEROBJECTID could not read the process user SID; not modelled by the local engine.") from error
    match = _SID.search(output.strip())
    if match is None:
        raise dax_typed.refusal("USEROBJECTID could not read the process user SID; not modelled by the local engine.")
    return match.group(1)
