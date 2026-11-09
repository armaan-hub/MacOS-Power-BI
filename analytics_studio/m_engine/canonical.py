"""Canonical text of an M value, in the format Power BI's answers are written in.

Rules (copied from the oracle format, not imported from tools/):
  null -> null          logical -> true | false
  number -> number:<R text, see number_text>, or number:NaN | number:+Infinity | number:-Infinity
  text -> text:"<escaped>"  (\\ for backslash, \\" for quote, \\n \\r \\t, \\uXXXX upper-case hex for
          other control characters U+0000-U+001F and U+007F; everything else as is)
  date -> date:yyyy-MM-dd   time -> time:HH:mm:ss.fffffff   datetime -> datetime:yyyy-MM-ddTHH:mm:ss.fffffff
  datetimezone -> datetimezone:yyyy-MM-ddTHH:mm:ss.fffffff+HH:mm   duration -> duration:<TimeSpan text>
  list -> list:[item,item]   record -> record:["name"=value,...]   table -> table:cols=[...];rows=[...]
  binary -> binary:<base64>   function -> function   type -> type
A value whose parts cannot be read (an error inside a lazy field) has no canonical text.
"""

from __future__ import annotations

import base64
import decimal
import math

from . import values as V
from .values import MError


def _round_digits(magnitude: float, count: int) -> tuple:
    """(digits, exponent10) of ``magnitude`` rounded half-up to ``count`` significant digits, trailing
    zeros dropped; value = 0.d1d2d3... * 10**exponent10 is NOT used: exponent10 is the decimal exponent
    of the first digit (scientific notation)."""
    with decimal.localcontext() as ctx:
        ctx.prec = count
        ctx.rounding = decimal.ROUND_HALF_UP
        rounded = +decimal.Decimal(magnitude)  # exact binary value, rounded to ``count`` digits
    _, digit_tuple, exponent = rounded.as_tuple()
    digits = "".join(str(d) for d in digit_tuple).rstrip("0") or "0"
    return digits, len(digit_tuple) - 1 + exponent


def _general(x: float, count: int) -> str:
    """.NET "G<count>" text of a finite non-zero double (scientific outside 1e-4 <= |x| < 10**count)."""
    digits, e = _round_digits(abs(x), count)
    if e < -4 or e >= count:
        mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        body = f"{mantissa}E{'+' if e >= 0 else '-'}{abs(e):02d}"
    elif e >= 0:
        body = digits + "0" * (e + 1 - len(digits)) if len(digits) <= e + 1 else digits[:e + 1] + "." + digits[e + 1:]
    else:
        body = "0." + "0" * (-e - 1) + digits
    return ("-" if x < 0 else "") + body


def number_text(x: float) -> str:
    """Text of a double, as Power BI's Number.ToText(v, "R", "en-US") writes it (rules in values.py)."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == math.floor(x):
        magnitude = abs(x)
        if magnitude < 2.0 ** 63 or x == -(2.0 ** 63):
            return str(int(x))  # also turns -0.0 into 0; -2**63 is the Int64 minimum (measured)
        if magnitude < 2.0 ** 96:
            digits, e = _round_digits(magnitude, 15)
            return ("-" if x < 0 else "") + digits + "0" * (e + 1 - len(digits))
    text = _general(x, 15)
    if float(text) != x:
        text = _general(x, 17)
    return text


def number_text_of(value: V.Number) -> str:
    """Text of a Number value: the exact literal text when it kept one, else the double's text."""
    return value.exact if value.exact is not None else number_text(value.value)


def escape_text(text: str) -> str:
    out = []
    for ch in text:
        n = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif n == 10:
            out.append("\\n")
        elif n == 13:
            out.append("\\r")
        elif n == 9:
            out.append("\\t")
        elif n < 32 or n == 127:
            out.append(f"\\u{n:04X}")
        else:
            out.append(ch)
    return "".join(out)


def _quoted(text: str) -> str:
    # Power BI's own serializer walks the text one UTF-16 unit at a time; a surrogate pair breaks it.
    if any(ord(ch) > 0xFFFF or 0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        raise MError("DataFormat.Error", "We couldn't convert to Number.")
    return '"' + escape_text(text) + '"'


def duration_text(ticks: int) -> str:
    """TimeSpan "c" text: [-][d.]hh:mm:ss[.fffffff]; days and fraction only when non-zero."""
    sign = "-" if ticks < 0 else ""
    rest = abs(ticks)
    days, rest = divmod(rest, V.TICKS_PER_DAY)
    hours, rest = divmod(rest, V.TICKS_PER_HOUR)
    minutes, rest = divmod(rest, V.TICKS_PER_MINUTE)
    seconds, fraction = divmod(rest, V.TICKS_PER_SECOND)
    text = (f"{days}." if days else "") + f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if fraction:
        text += f".{fraction:07d}"
    return sign + text


def _time_of_day(ticks: int) -> str:
    rest = ticks % V.TICKS_PER_DAY
    hours, rest = divmod(rest, V.TICKS_PER_HOUR)
    minutes, rest = divmod(rest, V.TICKS_PER_MINUTE)
    seconds, fraction = divmod(rest, V.TICKS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{fraction:07d}"


def _date_text(day) -> str:
    return f"{day.year:04d}-{day.month:02d}-{day.day:02d}"


def _datetime_text(ticks: int) -> str:
    return f"{_date_text(V.ticks_to_date(ticks))}T{_time_of_day(ticks)}"


def _offset_text(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{rest:02d}"


def to_canonical(value: V.MValue) -> str:
    """Canonical text of a value; raises MError when a lazy part of the value fails."""
    if isinstance(value, V.Null):
        return "null"
    if isinstance(value, V.Logical):
        return "true" if value.value else "false"
    if isinstance(value, V.Number):
        x = value.value
        if math.isnan(x):
            return "number:NaN"
        if x == math.inf:
            return "number:+Infinity"
        if x == -math.inf:
            return "number:-Infinity"
        return "number:" + number_text_of(value)
    if isinstance(value, V.Text):
        return "text:" + _quoted(value.value)
    if isinstance(value, V.Date):
        return "date:" + _date_text(value.value)
    if isinstance(value, V.Time):
        return "time:" + _time_of_day(value.ticks)
    if isinstance(value, V.DateTime):
        return "datetime:" + _datetime_text(value.ticks)
    if isinstance(value, V.DateTimeZone):
        return "datetimezone:" + _datetime_text(value.ticks) + _offset_text(value.offset_minutes)
    if isinstance(value, V.Duration):
        return "duration:" + duration_text(value.ticks)
    if isinstance(value, V.List):
        return "list:[" + ",".join(to_canonical(V.force(item)) for item in value.items) + "]"
    if isinstance(value, V.Record):
        parts = [_quoted(name) + "=" + to_canonical(V.force(item)) for name, item in value.fields]
        return "record:[" + ",".join(parts) + "]"
    if isinstance(value, V.Table):
        cols = ",".join(_quoted(name) + ":" + _quoted(kind.split("~")[0]) for name, kind in value.columns)  # "kind~TypeName~nullable"
        rows = ",".join("list:[" + ",".join(to_canonical(V.force(cell)) for cell in row) + "]" for row in value.rows)
        return f"table:cols=[{cols}];rows=[{rows}]"
    if isinstance(value, V.Binary):
        if value.bad:
            raise MError("DataFormat.Error", "We couldn't convert to Binary.")
        return "binary:" + base64.b64encode(value.value).decode("ascii")
    if isinstance(value, V.Function):
        return "function"
    if isinstance(value, V.TypeValue):
        return "type"
    raise MError("Expression.Error", "unknown value kind")
