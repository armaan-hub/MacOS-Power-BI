"""Power Query M formulas in custom columns, evaluated by the M engine (``analytics_studio/m_engine``).

``transformations._add_custom_column`` keeps its small evaluator for every formula that
``power_query_expression.compile_expression`` accepts. A formula that evaluator rejects is tried here:
``compile_m_formula`` parses it as ``each <formula>`` and ``evaluate_m_formula`` runs it on one row.

Exact-or-refuse: a row's answer is either the engine's answer (a value, or a genuine M error with its
reason and message) or ``MFormulaRefused`` when the engine has no measured answer for it (an engine
"is not supported by this engine yet" gap, an internal error, or a value this table model cannot store).
A refusal aborts the whole custom-column step; no guessed value is ever stored.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Any, Iterable, Iterator

from analytics_studio.m_engine import ast as A
from analytics_studio.m_engine import values as V
from analytics_studio.m_engine.canonical import number_text, number_text_of
from analytics_studio.m_engine.evaluator import apply_function, evaluate, root_env
from analytics_studio.m_engine.lexer import MSyntaxError
from analytics_studio.m_engine.parser import parse
from analytics_studio.m_engine.pbi_library_names import PBI_LIBRARY_NAMES
from analytics_studio.m_engine.stdlib import GLOBALS
from analytics_studio.m_engine.values import MError, Thunk
from analytics_studio.power_query_expression import ExpressionError as PowerQueryExpressionError
from analytics_studio.power_query_values import PowerQueryCellError


class MFormulaRefused(Exception):
    """The M engine has no measured Power BI answer for this formula or row; the step must be refused."""


class MStorageRefused(MFormulaRefused):
    """The engine has Power BI's answer but a custom-column cell cannot hold it (an infinite number, a list, a
    record, a duration, ...). No other evaluator may be tried: its answer for the same row would differ."""


_UNKNOWN_IMPORT = re.compile(r"^The import (\S+) matches no exports\.")


@dataclass(frozen=True)
class CompiledMFormula:
    """A parsed ``each`` formula: its function value and the Power BI library names it cannot run yet."""

    expression: str
    function: V.Function
    unsupported: tuple[str, ...]  # refusal messages for the names this engine cannot run
    unknown: tuple[str, ...]  # names that are neither Power Query library names nor bound by the formula


def compile_m_formula(expression: str, *, app_names: Iterable[str] = ()) -> CompiledMFormula:
    """Parse ``each <expression>``; a syntax error raises ``PowerQueryExpressionError`` with the parser's message.

    ``app_names`` are the app's own parameters and saved functions. The M engine does not see them, so a formula
    that refers to one is refused at evaluation instead of reading an unknown name as a Power Query error."""
    if not isinstance(expression, str) or not expression.strip():
        raise PowerQueryExpressionError("Enter a custom-column formula.")
    try:
        node = parse("each " + expression)
    except MSyntaxError as exc:
        raise PowerQueryExpressionError(exc.message) from exc
    except RecursionError as exc:
        raise PowerQueryExpressionError("The expression is nested too deeply.") from exc
    if not isinstance(node, A.EachExpr):
        raise PowerQueryExpressionError("Enter a custom-column formula.")
    names = set(_identifier_names(node))
    bound = set(_bound_names(node))
    unknown = tuple(sorted(
        name for name in names
        if name not in GLOBALS and name not in PBI_LIBRARY_NAMES and name not in bound and name != "_"
    ))
    unsupported = [
        f"The function {name} is not supported by this engine yet."
        for name in sorted(names) if name not in GLOBALS and name in PBI_LIBRARY_NAMES
    ]
    unsupported += [
        f"{name} is an app parameter or saved function, which custom columns do not pass to the M engine yet."
        for name in sorted(names & set(app_names))
    ]
    function = evaluate(node, root_env())
    return CompiledMFormula(expression, function, tuple(unsupported), unknown)


def evaluate_m_formula(compiled: CompiledMFormula, row: dict[str, Any]) -> Any:
    """Run one compiled formula on one row (the row is the record ``_``) and return the stored cell value.

    Returns ``m_to_cell`` of the result, or a ``PowerQueryCellError`` for a genuine M error. Raises
    ``MFormulaRefused`` when the engine has no measured answer for the formula or the row.
    """
    return evaluate_m_formula_traced(compiled, row)[0]


def evaluate_m_formula_traced(compiled: CompiledMFormula, row: dict[str, Any]) -> tuple[Any, bool]:
    """Like ``evaluate_m_formula``, also telling whether the formula read a text cell of the row.

    The app keeps imported columns as text until a type step converts them, so an M error on a text cell may be
    an untyped number or date rather than a Power BI text column; the caller decides what to do with that."""
    if compiled.unsupported:
        raise MFormulaRefused(compiled.unsupported[0])
    gaps_before = V.engine_gap_count()
    text_read = [False]
    try:
        record = _row_record(row, text_read)
        result = apply_function(compiled.function, [record])
        cell = m_to_cell(result)
    except MFormulaRefused:
        raise
    except MError as err:
        if V.engine_gap_count() != gaps_before:
            raise MFormulaRefused(_gap_message(err)) from err
        source_cell = getattr(err, "source_cell", None)
        if isinstance(source_cell, PowerQueryCellError):
            return source_cell, text_read[0]
        if _is_refusal(err):
            raise MFormulaRefused(err.message or "The formula is not supported by this engine yet.") from err
        return PowerQueryCellError(reason=err.reason, message=err.message or ""), text_read[0]
    except RecursionError as exc:
        raise MFormulaRefused("The evaluation is nested too deeply for this engine.") from exc
    except Exception as exc:  # noqa: BLE001 - an engine bug is a refusal, never a stored value
        raise MFormulaRefused(f"Internal evaluation error ({type(exc).__name__}).") from exc
    if V.engine_gap_count() != gaps_before:
        # An engine gap was hit and hidden by try ... otherwise (or a similar catch): the value is a guess.
        raise MFormulaRefused("The formula uses a function that is not supported by this engine yet.")
    return cell, text_read[0]


def _gap_message(err: MError) -> str:
    message = err.message or ""
    if "is not supported by this engine yet" in message:
        return message
    return "The formula uses a function that is not supported by this engine yet."


def usable_m_formula(expression: str, app_names: Iterable[str] = ()) -> CompiledMFormula | None:
    """The compiled formula when the M engine can in principle run it (it parses, every name is a library
    function this engine has, a field selector or bound by the formula, and no app parameter is used);
    otherwise None."""
    try:
        compiled = compile_m_formula(expression, app_names=app_names)
    except PowerQueryExpressionError:
        return None
    if compiled.unknown or compiled.unsupported:
        return None
    return compiled


def cell_to_m(value: Any) -> Any:
    """An app cell as an M value. A cell error becomes a thunk that raises the M error when it is read."""
    if value is None:
        return V.Null()
    if isinstance(value, PowerQueryCellError):
        return _error_thunk(value)
    if isinstance(value, bool):
        return V.Logical(value)
    if isinstance(value, Decimal):
        return _decimal_number(value)
    if isinstance(value, int):
        return V.Number(float(value))
    if isinstance(value, float):
        return V.Number(value)
    if isinstance(value, str):
        return V.Text(value)
    if isinstance(value, _dt.datetime):
        _refuse_zone(value)
        return V.DateTime(_ticks_of_day(value.time()) + (value.date().toordinal() - 1) * V.TICKS_PER_DAY)
    if isinstance(value, _dt.date):
        return V.Date(value)
    if isinstance(value, _dt.time):
        _refuse_zone(value)
        return V.Time(_ticks_of_day(value))
    raise MFormulaRefused(f"The cell type {type(value).__name__} is not supported by custom columns.")


def m_to_cell(value: Any) -> Any:
    """An M value as the app's cell representation. Any kind other than null, logical, number, text,
    date, datetime and time is refused, and so is a number that is not finite."""
    if isinstance(value, V.Null):
        return None
    if isinstance(value, V.Logical):
        return value.value
    if isinstance(value, V.Number):
        if not math.isfinite(value.value):
            raise MStorageRefused("A non-finite number cannot be stored in a custom column.")
        return Decimal(number_text_of(value))
    if isinstance(value, V.Text):
        return value.value
    if isinstance(value, V.Date):
        return value.value
    if isinstance(value, V.Time):
        return _time_of_ticks(value.ticks)
    if isinstance(value, V.DateTime):
        days, rest = divmod(value.ticks, V.TICKS_PER_DAY)
        try:
            day = _dt.date.fromordinal(days + 1)
        except (ValueError, OverflowError) as exc:
            raise MStorageRefused("The datetime is outside the supported range.") from exc
        return _dt.datetime.combine(day, _time_of_ticks(rest))
    kind = V.kind_of(value) if isinstance(value, V.MValue) else type(value).__name__
    raise MStorageRefused(f"A {kind} value cannot be stored in a custom column.")


# ---- helpers -----------------------------------------------------------------

def _is_refusal(err: MError) -> bool:
    message = err.message or ""
    if "is not supported by this engine yet" in message:
        return True
    match = _UNKNOWN_IMPORT.match(message)
    return bool(match and match.group(1) in PBI_LIBRARY_NAMES and match.group(1) not in GLOBALS)


def _identifier_names(node: Any) -> Iterator[str]:
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, A.Identifier):
            yield item.name
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, field.name) for field in fields(item))


def _bound_names(node: Any) -> Iterator[str]:
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, (A.LetBinding, A.Param)):
            yield item.name
        if isinstance(item, (list, tuple)):
            stack.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, field.name) for field in fields(item))


def _row_record(row: dict[str, Any], text_read: list[bool] | None = None) -> V.Record:
    fields_: list[tuple[str, Any]] = []
    for name, value in row.items():
        if text_read is not None and isinstance(value, str):
            fields_.append((str(name), _text_thunk(value, text_read)))
        else:
            fields_.append((str(name), cell_to_m(value)))
    return V.Record(tuple(fields_))


def _text_thunk(value: str, text_read: list[bool]) -> Thunk:
    def read() -> V.MValue:
        text_read[0] = True
        return V.Text(value)
    return Thunk(read)


def _error_thunk(cell: PowerQueryCellError) -> Thunk:
    def raise_error() -> V.MValue:
        err = MError(cell.reason, cell.message)
        err.source_cell = cell
        raise err
    return Thunk(raise_error)


def _decimal_number(value: Decimal) -> V.Number:
    if not value.is_finite():
        raise MFormulaRefused("A non-finite decimal cannot be read by the M engine.")
    as_double = float(value)
    plain = format(value, "f")
    exact = plain if plain != number_text(as_double) else None
    return V.Number(as_double, exact=exact)


def _ticks_of_day(value: _dt.time) -> int:
    seconds = value.hour * 3600 + value.minute * 60 + value.second
    return seconds * V.TICKS_PER_SECOND + value.microsecond * 10


def _time_of_ticks(ticks: int) -> _dt.time:
    seconds, sub = divmod(ticks, V.TICKS_PER_SECOND)
    if sub % 10:
        raise MStorageRefused("A time finer than a microsecond cannot be stored in a custom column.")
    hour, rest = divmod(seconds, 3600)
    minute, second = divmod(rest, 60)
    return _dt.time(hour, minute, second, sub // 10)


def _refuse_zone(value: Any) -> None:
    if value.tzinfo is not None:
        raise MFormulaRefused("Time zones cannot be read by custom columns.")
