"""Power Query M values.

Every value is an immutable class carrying ``meta`` (a Record value or None).
Date, time, datetime, datetimezone and duration use exact integer ticks (100 ns), so
arithmetic and text output match .NET without float error.

Numbers (measured live against Power BI Desktop, 2026-11-09, ~400 probes):
  * Every number has an IEEE double ``value``. All arithmetic, comparison and equality use
    that double (``123456789012345678 = 123456789012345679`` is true, ``1e21 = 1e21 + 1`` is
    true, ``0.1 + 0.2 = 0.3`` is false). The result of any operator is a plain double.
  * A number LITERAL (and its unary ``-``/``+``) that a double cannot hold in 15 significant
    digits or 15 decimal places, but a .NET Decimal can (|v| < 2^96, at most 28 decimals),
    also keeps its exact decimal text in ``exact`` and prints that text until the first
    operator touches it: ``123456789012345678``, ``3.14159265358979323846``, ``1e-16``,
    ``1.2345678901234567e20``, ``100000000000000000000.0`` (scale kept). Trailing fractional
    zeros are dropped before the decision (``1.000000000000000000`` is a plain double 1).
  * A double prints (``number_text`` in canonical.py): an integral value with |v| < 2^63 as its exact
    integer digits; an integral value with 2^63 <= |v| < 2^96 as 15 significant digits then
    zeros; anything else as .NET Framework "R" (15 significant digits if they round-trip,
    else 17; scientific ``1E-05`` / ``1E+29`` outside 1e-5 <= |v| < 1e15).

Errors are raised as ``MError`` (a Python exception) so that laziness, ``try`` and
``otherwise`` can catch them. A record field or list item that is not yet forced is a
``Thunk``; forcing it may raise.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

TICKS_PER_SECOND = 10_000_000
TICKS_PER_MINUTE = 60 * TICKS_PER_SECOND
TICKS_PER_HOUR = 60 * TICKS_PER_MINUTE
TICKS_PER_DAY = 24 * TICKS_PER_HOUR


_GAPS = threading.local()


def note_engine_gap() -> None:
    """Count one "not supported by this engine yet" error created on this thread (an engine gap, not a Power BI
    answer). A caller that must never store a guessed value compares ``engine_gap_count`` before and after an
    evaluation: ``try ... otherwise`` and similar catch sites cannot hide a gap from it."""
    _GAPS.count = getattr(_GAPS, "count", 0) + 1


def engine_gap_count() -> int:
    return getattr(_GAPS, "count", 0)


class MError(Exception):
    """An M error in flight. Fields mirror the M error record."""

    def __init__(self, reason: str, message: Optional[str], detail: Any = None,
                 fmt: Optional[str] = None, params: Optional[tuple] = None, code: Optional[str] = None):
        super().__init__(message or "")
        if message and "is not supported by this engine yet" in message:
            note_engine_gap()
        self.reason = reason
        self.message = message
        self.detail = detail
        self.fmt = fmt
        self.params = params
        self.code = code


class Thunk:
    """A lazily evaluated value; evaluated at most once (a failed evaluation is not cached)."""

    __slots__ = ("_fn", "_value", "_busy")

    def __init__(self, fn: Callable[[], Any]):
        self._fn = fn
        self._value: Any = None
        self._busy = False

    def force(self) -> "MValue":
        if self._value is None:
            if self._busy:
                raise MError("Expression.Error", "A cyclic reference was encountered during evaluation.")
            self._busy = True
            try:
                self._value = self._fn()
            finally:
                self._busy = False
        return self._value


def force(item: Any) -> "MValue":
    return item.force() if isinstance(item, Thunk) else item


class MValue:
    """Base class of every M value (no fields of its own)."""


@dataclass(frozen=True, eq=False)
class Null(MValue):
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class Logical(MValue):
    value: bool
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class Number(MValue):
    value: float
    meta: Optional["Record"] = None
    exact: Optional[str] = None  # exact decimal text of a literal a double cannot hold; see module docstring
    subtype: Optional[str] = None  # "Int64" on a whole-number custom-column cell (Value.Type of it is not measured)


@dataclass(frozen=True, eq=False)
class Text(MValue):
    value: str
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class Date(MValue):
    value: _dt.date
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class Time(MValue):
    ticks: int  # 0 <= ticks < TICKS_PER_DAY
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class DateTime(MValue):
    ticks: int  # ticks since 0001-01-01T00:00:00
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class DateTimeZone(MValue):
    ticks: int  # local wall-clock ticks since 0001-01-01T00:00:00
    offset_minutes: int
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class Duration(MValue):
    ticks: int
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class Binary(MValue):
    value: bytes
    meta: Optional["Record"] = None
    bad: bool = False  # built from out-of-range numbers: Power BI cannot serialize it


@dataclass(frozen=True, eq=False)
class List(MValue):
    items: tuple  # MValue or Thunk items (lists are built eagerly; items are values)
    meta: Optional["Record"] = None
    # Table.FromColumns types a column from its list's item type. A list written in the query (or joined with &)
    # has item type any (``literal``); a list read from a typed table column carries that column's kind in
    # ``item_kind``. Any other list has an item type this engine does not track.
    literal: bool = False
    item_kind: Optional[str] = None


@dataclass(frozen=True, eq=False)
class Record(MValue):
    fields: tuple  # ((name, MValue | Thunk), ...) in field order
    meta: Optional["Record"] = None

    def names(self) -> tuple:
        return tuple(name for name, _ in self.fields)

    def get(self, name: str) -> Optional[MValue]:
        for field_name, item in self.fields:
            if field_name == name:
                return force(item)
        return None

    def has(self, name: str) -> bool:
        return any(field_name == name for field_name, _ in self.fields)


@dataclass(frozen=True, eq=False)
class Table(MValue):
    columns: tuple  # ((name, kind), ...)
    rows: tuple  # tuple of tuples of MValue
    meta: Optional["Record"] = None


@dataclass(frozen=True, eq=False)
class ParamSpec:
    name: str
    type_: Optional["TypeValue"] = None
    optional: bool = False


@dataclass(frozen=True, eq=False)
class Function(MValue):
    params: tuple  # ParamSpec
    invoke: Callable[[list], MValue] = field(repr=False)  # receives the lazy argument list
    return_type: Optional["TypeValue"] = None
    meta: Optional["Record"] = None
    # How a function written in M was built: "closure", or "identity" for a function whose body is just its
    # only parameter (``each _``, ``(x) => x``). None for library functions. Table functions read it.
    origin: Optional[str] = None
    # Function.From: the arguments are passed on as given, whatever their number or type (measured)
    variadic: bool = False


@dataclass(frozen=True, eq=False)
class TypeValue(MValue):
    """A type value. ``name`` is a primitive name ("number", "list", "record", ...) or "any"."""
    name: str
    nullable: bool = False
    meta: Optional["Record"] = None
    fields: Optional[tuple] = None  # record types only: ((name, TypeValue, optional), ...) in declared order
    label: Optional[str] = None  # the Table.Schema TypeName of a subtype constant (Int64.Type), else None
    open_record: bool = False  # record types: [a = number, ...]
    # function types: ((name, TypeValue, optional), ...) parameters and the return TypeValue (None: not declared)
    signature: Optional[tuple] = None
    item: Optional["TypeValue"] = None  # list types: {T}
    facets: Optional[tuple] = None  # Type.ReplaceFacets: the ten facet values in Type.Facets order
    raw_fields: Optional["Record"] = None  # Type.ForRecord: the field record as given (read back unchanged)


# ---- names used in messages and type checks -------------------------------

DISPLAY = {
    "null": "Null", "logical": "Logical", "number": "Number", "text": "Text", "date": "Date",
    "time": "Time", "datetime": "DateTime", "datetimezone": "DateTimeZone", "duration": "Duration",
    "binary": "Binary", "list": "List", "record": "Record", "table": "Table", "function": "Function",
    "type": "Type", "any": "Any", "anynonnull": "Any",
}


def kind_of(value: MValue) -> str:
    if isinstance(value, Null):
        return "null"
    for cls, name in _KIND_NAMES:
        if isinstance(value, cls):
            return name
    raise TypeError(f"not an M value: {value!r}")


_KIND_NAMES = (
    (Logical, "logical"), (Number, "number"), (Text, "text"), (Date, "date"), (Time, "time"),
    (DateTime, "datetime"), (DateTimeZone, "datetimezone"), (Duration, "duration"),
    (Binary, "binary"), (List, "list"), (Record, "record"), (Table, "table"),
    (Function, "function"), (TypeValue, "type"),
)


def type_display(value: MValue) -> str:
    return DISPLAY[kind_of(value)]


def with_meta(value: MValue, meta: Optional[Record]) -> MValue:
    """Return the same value with new metadata."""
    kwargs = {"meta": meta}
    return type(value)(**{f: getattr(value, f) for f in _fields_of(value)}, **kwargs)


def _fields_of(value: MValue) -> list[str]:
    return [f for f in value.__dataclass_fields__ if f != "meta"]  # type: ignore[attr-defined]


def is_type(value: MValue, t: TypeValue) -> bool:
    """``value is T``. Null matches only nullable types, null, and any."""
    if isinstance(value, Null):
        return t.nullable or t.name in ("null", "any")
    if t.name == "any" or t.name == "anynonnull":
        return True
    if t.name == "null":
        return False
    return kind_of(value) == t.name


def _seconds_literal(rest_ticks: int) -> str:
    """Seconds (with their fraction) as an M literal argument: 5, 5.5, 5.0000001."""
    seconds, fraction = divmod(rest_ticks, TICKS_PER_SECOND)
    return str(seconds) if not fraction else f"{seconds}.{fraction:07d}".rstrip("0")


def _clock_parts(ticks: int) -> tuple:
    rest = ticks % TICKS_PER_DAY
    hours, rest = divmod(rest, TICKS_PER_HOUR)
    minutes, rest = divmod(rest, TICKS_PER_MINUTE)
    return hours, minutes, _seconds_literal(rest)


def describe_value(value: MValue) -> str:
    """How a value appears in a conversion message: null, true, 1, "text", #date(2024, 1, 2)."""
    if isinstance(value, Null):
        return "null"
    if isinstance(value, Logical):
        return "true" if value.value else "false"
    if isinstance(value, Number):
        if value.value != value.value:
            return "#nan"
        if value.value in (float("inf"), float("-inf")):
            return "#infinity" if value.value > 0 else "-#infinity"
        from .canonical import number_text_of  # local import: canonical depends on values
        return number_text_of(value)
    if isinstance(value, Text):
        return '"' + value.value.replace('"', '""') + '"'
    if isinstance(value, Date):
        return f"#date({value.value.year}, {value.value.month}, {value.value.day})"
    if isinstance(value, Time):
        h, m, s = _clock_parts(value.ticks)
        return f"#time({h}, {m}, {s})"
    if isinstance(value, (DateTime, DateTimeZone)):
        day = ticks_to_date(value.ticks)
        h, m, s = _clock_parts(value.ticks)
        base = f"{day.year}, {day.month}, {day.day}, {h}, {m}, {s}"
        if isinstance(value, DateTimeZone):
            off_h, off_m = divmod(abs(value.offset_minutes), 60)
            sign = -1 if value.offset_minutes < 0 else 1
            return f"#datetimezone({base}, {sign * off_h}, {sign * off_m})"
        return f"#datetime({base})"
    if isinstance(value, Duration):
        rest = abs(value.ticks)
        days, rest = divmod(rest, TICKS_PER_DAY)
        hours, rest = divmod(rest, TICKS_PER_HOUR)
        minutes, rest = divmod(rest, TICKS_PER_MINUTE)
        sign = "-" if value.ticks < 0 else ""
        return f"#duration({sign}{days}, {sign}{hours}, {sign}{minutes}, {sign}{_seconds_literal(rest)})"
    return type_display(value)


def convert_error(value: MValue, t: TypeValue) -> MError:
    target = DISPLAY.get(t.name, t.name)
    if isinstance(value, (List, Record, Binary, Table, Function)):
        shown_type = type_display(value)
        message = f"We cannot convert a value of type {shown_type} to type {target}."
        return MError("Expression.Error", message,
                      detail=Record((("Value", value), ("Type", TypeValue(t.name)))),
                      fmt="We cannot convert a value of type #{0} to type #{1}.",
                      params=(Text(shown_type), Text(target)), code="10276")
    if isinstance(value, TypeValue):
        return MError("Expression.Error", f"We cannot convert Type to {target} type.",
                      detail=Record((("Value", value), ("Type", value))),
                      fmt="We cannot convert Type to #{0} type.", params=(Text(target),), code="10278")
    shown = describe_value(value)
    return MError("Expression.Error", f"We cannot convert the value {shown} to type {target}.",
                  detail=Record((("Value", value), ("Type", TypeValue(t.name)))),
                  fmt="We cannot convert the value #{0} to type #{1}.",
                  params=(Text(shown), Text(target)), code="10277")


def check_type(value: MValue, t: TypeValue) -> MValue:
    """``value as T``: returns the value, or raises the conversion error."""
    if is_type(value, t):
        return value
    raise convert_error(value, t)


def operator_error(op: str, left: MValue, right: MValue) -> MError:
    left_type, right_type = type_display(left), type_display(right)
    return MError("Expression.Error", f"We cannot apply operator {op} to types {left_type} and {right_type}.",
                  detail=Record((("Operator", Text(op)), ("Left", left), ("Right", right))),
                  fmt="We cannot apply operator #{0} to types #{1} and #{2}.",
                  params=(Text(op), Text(left_type), Text(right_type)), code="10051")


def unary_error(op: str, value: MValue) -> MError:
    shown = type_display(value)
    return MError("Expression.Error", f"We cannot apply operator {op} to the type {shown}.",
                  detail=Record((("Operator", Text(op)), ("Value", value))),
                  fmt="We cannot apply operator #{0} to the type #{1}.",
                  params=(Text(op), Text(shown)), code="10078")


def field_access_error(target: MValue, name: str) -> MError:
    shown = type_display(target)
    return MError("Expression.Error", f"We cannot apply field access to the type {shown}.",
                  detail=Record((("Value", target), ("Key", Text(name)))),
                  fmt="We cannot apply field access to the type #{0}.", params=(Text(shown),), code="10335")


def generic_error(message: str) -> MError:
    return MError("Expression.Error", message, fmt=message)


# ---- date, time and duration arithmetic on ticks -----------------------------

def date_ticks(day: _dt.date) -> int:
    return (day.toordinal() - 1) * TICKS_PER_DAY


def ticks_to_date(ticks: int) -> _dt.date:
    return _dt.date.fromordinal(ticks // TICKS_PER_DAY + 1)


def time_ticks(hour: int, minute: int, second: float) -> int:
    return hour * TICKS_PER_HOUR + minute * TICKS_PER_MINUTE + round(second * TICKS_PER_SECOND)


_RANGE_CODES = {"Date": "10019", "Time": "10023", "DateTime": "10027", "DateTimeZone": "10031"}
_RANGE_TEXT = "The {} operation failed because the resulting value falls outside the range of allowed values."
INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1
MAX_DATETIME_TICKS = 3652059 * TICKS_PER_DAY - 1  # 9999-12-31T23:59:59.9999999
INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1


def range_error(kind: str) -> MError:
    """The error for a Date/Time/DateTime/DateTimeZone result outside its range."""
    message = _RANGE_TEXT.format(kind)
    return MError("Expression.Error", message, fmt=message, code=_RANGE_CODES.get(kind))


def duration_range_error() -> MError:
    message = ("The Duration operation failed because the resulting duration falls outside the range of "
               "allowed values.")
    return MError("Expression.Error", message, fmt=message, code="10033")


def make_duration(ticks: int) -> Duration:
    if not INT64_MIN <= ticks <= INT64_MAX:
        raise duration_range_error()
    return Duration(ticks)


def make_datetime(ticks: int) -> DateTime:
    if not 0 <= ticks <= MAX_DATETIME_TICKS:
        raise range_error("DateTime")
    return DateTime(ticks)


def make_date_from_ticks(ticks: int) -> Date:
    """The Date holding the day that contains ``ticks`` (floored to the day)."""
    if not 0 <= ticks <= MAX_DATETIME_TICKS:
        raise range_error("Date")
    return Date(ticks_to_date(ticks))


def make_time(ticks: int) -> Time:
    return Time(ticks % TICKS_PER_DAY)


def make_datetimezone(local_ticks: int, offset_minutes: int) -> DateTimeZone:
    """Local wall-clock and UTC instant must both lie in the DateTime range; offset within +-14:00."""
    utc = local_ticks - offset_minutes * TICKS_PER_MINUTE
    if (abs(offset_minutes) > 840 or not 0 <= local_ticks <= MAX_DATETIME_TICKS
            or not 0 <= utc <= MAX_DATETIME_TICKS):
        raise range_error("DateTimeZone")
    return DateTimeZone(local_ticks, offset_minutes)


def to_int32(value: "MValue") -> int:
    """A Number argument that must be a 32-bit integer (``#date(2024.5,1,1)`` is an error)."""
    if not isinstance(value, Number):
        raise convert_error(value, TypeValue("number"))
    x = value.value
    if x != x or x in (float("inf"), float("-inf")) or x != int(x) or not INT32_MIN <= x <= INT32_MAX:
        message = "The number is out of range of a 32 bit integer value."
        raise MError("Expression.Error", message, detail=value, fmt=message, code="10108")
    return int(x)


def split_datetime_ticks(ticks: int) -> tuple[_dt.date, int]:
    return ticks_to_date(ticks), ticks % TICKS_PER_DAY


def utc_ticks(value: DateTimeZone) -> int:
    return value.ticks - value.offset_minutes * TICKS_PER_MINUTE


# ---- number literals ---------------------------------------------------------

_DECIMAL_LIMIT = 2 ** 96  # System.Decimal holds integers below this, with at most 28 decimals


def number_from_literal(text: str) -> Number:
    """The Number for a numeric literal (hex or decimal text); see the module docstring."""
    if text[:2] in ("0x", "0X"):
        text = str(min(int(text[2:], 16), 2 ** 64 - 1))  # a hex literal saturates at the unsigned 64-bit maximum
    with _decimal.localcontext() as ctx:
        ctx.prec = 100
        ctx.traps[_decimal.Overflow] = False
        d = _decimal.Decimal(text)
        sign, digits, exponent = d.as_tuple()
        if not any(digits):
            return Number(0.0)
        value = float(text)
        # Drop trailing fractional zeros for the decision only.
        digit_list = list(digits)
        scale = -exponent
        while scale > 0 and digit_list and digit_list[-1] == 0:
            digit_list.pop()
            scale -= 1
        significant = len(digit_list) + (exponent if exponent > 0 else 0)
        if significant <= 15 and max(scale, 0) <= 15:
            return Number(value)
        # Does a Decimal hold it?  Excess decimals round to 28 places; a result of zero does not count.
        shown = d
        if exponent < -28:
            shown = d.quantize(_decimal.Decimal(1).scaleb(-28), rounding=_decimal.ROUND_HALF_UP)
            if not any(shown.as_tuple().digits):
                return Number(value)
        if abs(shown) >= _DECIMAL_LIMIT:
            return Number(value)
        return Number(value, exact=format(shown, "f"))
