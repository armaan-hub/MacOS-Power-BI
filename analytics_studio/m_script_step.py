"""The ``m_script`` step (Task 111, m-script-101): a whole ``let ... in`` M script run on the M engine.

The script's first binding names the source (``source_binding``, "Source" in the editor). That binding's own
expression is not evaluated: the name is bound to the input candidate as a typed M table, each cell read as its
column's type (the same typed cells a custom column reads, see ``transformations._typed_rows_for_formula``). The
remaining bindings run on the M engine and the result must be a table.

Exact or refused: the result is converted back to an ``ImportCandidate`` only when every column has a type the app
can store and every cell is a value of that type. A genuine M cell error becomes a ``PowerQueryCellError`` cell. A
table-level M error, an engine gap ("... is not supported by this engine yet.") or anything the table cannot hold
raises ``TransformationError`` and the step is refused; no value is guessed.

The output column types (``output_types``) are the table type the engine gives the script: they are read by running
the script on the same columns with no rows, because the engine's column types do not depend on the rows.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any

from analytics_studio.m_custom_column import MStorageRefused, cell_to_m, m_to_cell
from analytics_studio.m_engine import ast as A
from analytics_studio.m_engine import values as V
from analytics_studio.m_engine.evaluator import Env, evaluate, root_env
from analytics_studio.m_engine.lexer import MSyntaxError
from analytics_studio.m_engine.parser import parse
from analytics_studio.power_query_values import PowerQueryCellError

# app model type -> the M column kind (the Table.Schema TypeName a Changed Type step gives it)
_KIND_OF_APP_TYPE = {
    "text": "text~Text.Type~1",
    "whole_number": "number~Int64.Type~1",
    "decimal_number": "number~Number.Type~1",
    "boolean": "logical~Logical.Type~1",
    "date": "date~Date.Type~1",
    "datetime": "datetime~DateTime.Type~1",
    "time": "time~Time.Type~1",
    "any": "any",
}
_APP_TYPE_OF_BASE = {
    "text": "text", "logical": "boolean", "date": "date", "datetime": "datetime", "time": "time", "any": "any",
}
_NUMBER_TYPE_NAMES = {"Number.Type": "decimal_number", "Currency.Type": "decimal_number",
                      "Percentage.Type": "decimal_number", "Int64.Type": "whole_number"}


def _refuse(message: str) -> Exception:
    from analytics_studio.transformations import TransformationError  # local: transformations imports this module

    return TransformationError(message)


def _app_type_of_kind(kind: str) -> str:
    """The app model type of an M column kind; a kind the app cannot store is refused."""
    base, _, rest = kind.partition("~")
    type_name = rest.split("~")[0] if rest else ""
    if base == "number":
        if type_name == "":
            return "decimal_number"
        if type_name in _NUMBER_TYPE_NAMES:
            return _NUMBER_TYPE_NAMES[type_name]
        raise _refuse(f"A {type_name} column cannot be stored by a Power Query script step.")
    if base in _APP_TYPE_OF_BASE:
        return _APP_TYPE_OF_BASE[base]
    raise _refuse(f"A {base} column cannot be stored by a Power Query script step.")


def _kind_of_app_type(app_type: str) -> str:
    kind = _KIND_OF_APP_TYPE.get(app_type)
    if kind is None:
        raise _refuse(f"The column type {app_type!r} is not supported by a Power Query script step.")
    return kind


def _script_bindings(script: str, source_binding: str) -> tuple[A.LetExpr, A.LetExpr]:
    """The parsed script and the let expression that runs its bindings after the source binding."""
    try:
        node = parse(script)
    except MSyntaxError as exc:
        raise _refuse(f"The M script has a syntax error: {exc.message}") from exc
    if not isinstance(node, A.LetExpr) or not node.bindings:
        raise _refuse("The M script must be a let expression.")
    if node.bindings[0].name != source_binding:
        raise _refuse(f"The first binding of the M script must be {source_binding}.")
    return node, A.LetExpr(bindings=tuple(node.bindings[1:]), body=node.body)


def _typed_cell(value: Any) -> V.MValue:
    """One typed cell of the input as an M value. A cell that did not convert refuses the step."""
    from analytics_studio.m_custom_column import UnconvertedCell  # local: keeps the import graph acyclic

    if isinstance(value, UnconvertedCell):
        raise _refuse(f"A cell cannot be read by the Power Query script: {value.message}")
    return cell_to_m(value)


def _run(script: str, source_binding: str, headers: list[str], kinds: list[str], rows: list[tuple]) -> V.MValue:
    """Evaluate the script with the source bound to a table of ``rows`` (cells already M values)."""
    node, rest = _script_bindings(script, source_binding)
    table = V.Table(tuple(zip(headers, kinds)), tuple(rows))
    scope = Env({source_binding: table}, root_env())
    gaps_before = V.engine_gap_count()
    try:
        value = evaluate(rest, scope)
    except V.MError as err:
        if V.engine_gap_count() != gaps_before or "is not supported by this engine yet" in (err.message or ""):
            raise _refuse(err.message or "The M script uses a function that is not supported by this engine yet.")
        raise _refuse(f"The M script failed: {err.message or err.reason}") from err
    except RecursionError as exc:
        raise _refuse("The M script is nested too deeply for this engine.") from exc
    except Exception as exc:  # noqa: BLE001 - an engine bug is a refusal, never a stored value
        raise _refuse(f"Internal evaluation error ({type(exc).__name__}).") from exc
    if V.engine_gap_count() != gaps_before:
        raise _refuse("The M script uses a function that is not supported by this engine yet.")
    if not isinstance(value, V.Table):
        raise _refuse("The M script must return a table.")
    return value


def output_types(headers: list[str], column_types: dict[str, str], script: str, source_binding: str) -> dict[str, str]:
    """The app types of the script's output columns, from the engine's table type (no rows are read)."""
    kinds = [_kind_of_app_type(column_types.get(header, "text")) for header in headers]
    table = _run(script, source_binding, headers, kinds, [])
    return {name: _app_type_of_kind(kind) for name, kind in table.columns}


def run_m_script(candidate: Any, script: str, source_binding: str, column_types: dict[str, str]) -> Any:
    """The candidate after the script (an ImportCandidate). Raises TransformationError when the step is refused."""
    from analytics_studio.file_import import ImportCandidate
    from analytics_studio.transformations import TransformationError, _typed_rows_for_formula

    headers = list(candidate.headers)
    typed = _typed_rows_for_formula(candidate.rows, {header: column_types.get(header, "text") for header in headers})
    kinds = [_kind_of_app_type(column_types.get(header, "text")) for header in headers]
    rows = [tuple(_typed_cell(row.get(header)) for header in headers) for row in typed]
    table = _run(script, source_binding, headers, kinds, rows)
    out_headers = [name for name, _ in table.columns]
    out_types = [_app_type_of_kind(kind) for _, kind in table.columns]
    try:
        out_rows = [
            {name: _stored_cell(cell, app_type) for name, app_type, cell in zip(out_headers, out_types, row)}
            for row in table.rows
        ]
    except TransformationError:
        raise
    except RecursionError as exc:
        raise _refuse("The M script is nested too deeply for this engine.") from exc
    except Exception as exc:  # noqa: BLE001 - an engine bug is a refusal, never a stored value
        raise _refuse(f"Internal evaluation error ({type(exc).__name__}).") from exc
    return ImportCandidate(
        kind=candidate.kind,
        headers=out_headers,
        rows=out_rows,
        options=dict(candidate.options),
        notices=list(candidate.notices),
        source_id=candidate.source_id,
    )


def _stored_cell(cell: Any, app_type: str) -> Any:
    """A table cell as the app stores it. A genuine M error is an error cell; a value of the wrong type is refused."""
    try:
        value = V.force(cell)
    except V.MError as err:
        if "is not supported by this engine yet" in (err.message or ""):
            raise _refuse(err.message or "The M script uses a function that is not supported by this engine yet.")
        return PowerQueryCellError(reason=err.reason, message=err.message or "")
    try:
        stored = m_to_cell(value)
    except MStorageRefused as exc:
        raise _refuse(str(exc)) from exc
    if stored is None:
        return None
    if app_type == "whole_number":
        if not isinstance(stored, Decimal) or stored != stored.to_integral_value():
            raise _refuse("A whole-number column holds a value that is not a whole number.")
        return int(stored)
    if app_type == "decimal_number":
        if not isinstance(stored, Decimal):
            raise _refuse("A number column holds a value that is not a number.")
        return stored
    if app_type == "boolean":
        if not isinstance(stored, bool):
            raise _refuse("A logical column holds a value that is not logical.")
        return stored
    if app_type in ("text", "date", "datetime", "time"):
        expected = {"text": str, "date": _dt.date, "datetime": _dt.datetime, "time": _dt.time}[app_type]
        # a datetime is a date too: an exact type test keeps a date column from holding a datetime
        if type(stored) is not expected:
            raise _refuse(f"A {app_type} column holds a value of another type.")
        return stored
    return stored  # any: the value as the engine gives it, a value this table can store
