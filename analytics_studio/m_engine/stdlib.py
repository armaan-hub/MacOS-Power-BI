"""Built-in functions and intrinsic constructors for the M evaluator.

Only what the battery calls, plus the constructors the battery uses (``#date`` and friends).
Each native receives its arguments forced (a missing optional argument is null).
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Callable

from . import values as V
from .canonical import duration_text, number_text_of
from .values import MError, MValue, ParamSpec


def _native(params: tuple, fn: Callable[..., MValue]) -> V.Function:
    """params: ((name, optional), ...). ``fn`` gets forced MValues, one per param."""
    specs = tuple(ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke)


def _number(value: MValue) -> float:
    if isinstance(value, V.Number):
        return value.value
    raise V.convert_error(value, V.TypeValue("number"))


def _integer(value: MValue) -> int:
    return V.to_int32(value)


def _text(value: MValue) -> str:
    if isinstance(value, V.Text):
        return value.value
    raise V.convert_error(value, V.TypeValue("text"))


def _seconds_ticks(second: float, kind: str) -> int:
    if math.isnan(second) or math.isinf(second):
        raise V.range_error(kind)
    return round(second * V.TICKS_PER_SECOND)


def _days_from(year: int, month: int, day: int, kind: str) -> _dt.date:
    try:
        return _dt.date(year, month, day)
    except (ValueError, OverflowError):
        raise V.range_error(kind)


def _date(year: MValue, month: MValue, day: MValue) -> MValue:
    y, m, d = _integer(year), _integer(month), _integer(day)
    return V.Date(_days_from(y, m, d, "Date"))


def _clock(hour: int, minute: int, second: float, kind: str, max_hour: int) -> int:
    """Ticks into the day; #time accepts 24:00:00 (max_hour 24) as midnight, #datetime does not."""
    seconds = _seconds_ticks(second, kind)
    if not (0 <= hour <= max_hour and 0 <= minute < 60 and 0 <= seconds < 60 * V.TICKS_PER_SECOND):
        raise V.range_error(kind)
    total = hour * V.TICKS_PER_HOUR + minute * V.TICKS_PER_MINUTE + seconds
    if total > V.TICKS_PER_DAY:
        raise V.range_error(kind)
    return total


def _time(hour: MValue, minute: MValue, second: MValue) -> MValue:
    h, m = _integer(hour), _integer(minute)
    return V.Time(_clock(h, m, _number(second), "Time", 24) % V.TICKS_PER_DAY)


def _local_ticks(parts: tuple, kind: str) -> int:
    y, mo, d, h, mi = (_integer(p) for p in parts[:5])
    clock = _clock(h, mi, _number(parts[5]), kind, 23)
    return V.date_ticks(_days_from(y, mo, d, kind)) + clock


def _datetime(*parts: MValue) -> MValue:
    return V.DateTime(_local_ticks(parts, "DateTime"))


def _datetimezone(*parts: MValue) -> MValue:
    local = _local_ticks(parts, "DateTimeZone")
    off_hours, off_minutes = _integer(parts[6]), _integer(parts[7])
    return V.make_datetimezone(local, off_hours * 60 + off_minutes)


def _duration(days: MValue, hours: MValue, minutes: MValue, seconds: MValue) -> MValue:
    d, h, m = _integer(days), _integer(hours), _integer(minutes)
    s = _number(seconds)
    if math.isnan(s) or math.isinf(s):
        raise V.duration_range_error()
    total = (d * V.TICKS_PER_DAY + h * V.TICKS_PER_HOUR + m * V.TICKS_PER_MINUTE
             + round(s * V.TICKS_PER_SECOND))
    return V.make_duration(total)


def _binary(items: MValue) -> MValue:
    """#binary({bytes}). Power BI builds a binary even from out-of-range numbers, but its serializer then
    fails on it (UNREPRESENTABLE); ``bad`` reproduces that."""
    if isinstance(items, V.Null):
        raise MError("DataFormat.Error", "We couldn't convert to Binary.")
    if isinstance(items, V.Text):
        raise MError("Expression.Error", "Invalid binary encoding.")
    if not isinstance(items, V.List):
        raise V.convert_error(items, V.TypeValue("list"))
    data = bytearray()
    bad = False
    for item in items.items:
        cell = V.force(item)
        if not isinstance(cell, V.Number):
            raise V.convert_error(cell, V.TypeValue("number"))
        x = cell.value
        if x != x or x != math.floor(x) or not 0 <= x <= 255:
            bad = True
        else:
            data.append(int(x))
    return V.Binary(bytes(data), bad=bad)


_EN_US = ("", "en-us", "en", "en-gb", "en-au", "en-ca", "en-ie", "en-in", "en-nz", "en-za")  # same upper-casing


def _culture_name(value: MValue) -> str:
    """The culture argument (null = current culture, which is en-US here), lower-cased."""
    if isinstance(value, V.Null):
        return ""
    return _text(value).lower()


_LANGUAGES = frozenset(
    "aa ab af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee "
    "el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io "
    "is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn "
    "mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se "
    "sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo "
    "wa wo xh yi yo za zh zu".split())


def _unsupported_culture(name: str) -> MError:
    """A name that is no culture at all is Power BI's DataFormat.Error; a real culture this engine has no
    formatting rules for yet gets a distinct message so nobody mistakes it for Power BI's answer."""
    if name.split("-")[0] not in _LANGUAGES:
        return MError("DataFormat.Error", "The specified culture is not supported.")
    return MError("Expression.Error", f"The culture '{name}' is not supported by this engine yet.")


# Lower-case letters whose upper-case partner .NET Framework's casing tables (Unicode 6) do not have.
_NO_UPPER_RANGES = ((0x10D0, 0x10FF), (0x13F8, 0x13FD), (0x1C80, 0x1C8F), (0xAB70, 0xABBF))


def _upper_unit(ch: str, turkic: bool) -> str:
    """Simple (one character to one character) upper-casing of a UTF-16 code unit, like .NET ToUpper."""
    code = ord(ch)
    if code > 0xFFFF or any(low <= code <= high for low, high in _NO_UPPER_RANGES):
        return ch
    if turkic and ch == "i":
        return "\u0130"
    upper = ch.upper()
    if len(upper) == 1:
        return upper
    title = ch.title()  # Greek letters with iota subscript: simple upper-case is the title-case form
    return title if len(title) == 1 else ch


def _text_upper(value: MValue, culture: MValue = V.Null()) -> MValue:
    name = _culture_name(culture)
    if name not in _EN_US and not name.startswith(("tr", "az")):
        raise _unsupported_culture(name)
    if isinstance(value, V.Null):
        return V.Null()
    turkic = name.startswith(("tr", "az"))
    return V.Text("".join(_upper_unit(ch, turkic) for ch in _text(value)))


def _utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _text_length(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    return V.Number(float(_utf16_length(_text(value))))


def _twelve_hour(ticks: int) -> tuple:
    rest = ticks % V.TICKS_PER_DAY
    hours, rest = divmod(rest, V.TICKS_PER_HOUR)
    minutes, rest = divmod(rest, V.TICKS_PER_MINUTE)
    seconds = rest // V.TICKS_PER_SECOND
    return (hours % 12 or 12), minutes, seconds, ("AM" if hours < 12 else "PM")


def _text_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    """en-US text of a value, as Power BI's Text.From writes it (measured live)."""
    name = _culture_name(culture)
    if name not in ("", "en-us"):  # other English cultures format dates differently (measured: en-GB)
        raise _unsupported_culture(name)
    if isinstance(value, (V.Null, V.Text)):
        return value
    if isinstance(value, V.Number):
        x = value.value
        if math.isnan(x):
            return V.Text("NaN")
        if math.isinf(x):
            return V.Text("\u221e" if x > 0 else "-\u221e")
        return V.Text(number_text_of(value))
    if isinstance(value, V.Logical):
        return V.Text("true" if value.value else "false")
    if isinstance(value, V.Duration):
        return V.Text(duration_text(value.ticks))
    if isinstance(value, V.Date):
        return V.Text(_us_date(value.value))
    if isinstance(value, V.Time):
        hour, minute, _, marker = _twelve_hour(value.ticks)
        return V.Text(f"{hour}:{minute:02d} {marker}")
    if isinstance(value, (V.DateTime, V.DateTimeZone)):
        hour, minute, second, marker = _twelve_hour(value.ticks)
        text = f"{_us_date(V.ticks_to_date(value.ticks))} {hour}:{minute:02d}:{second:02d} {marker}"
        if isinstance(value, V.DateTimeZone):
            sign = "+" if value.offset_minutes >= 0 else "-"
            off_h, off_m = divmod(abs(value.offset_minutes), 60)
            text += f" {sign}{off_h:02d}:{off_m:02d}"
        return V.Text(text)
    raise V.convert_error(value, V.TypeValue("text"))


def _us_date(day: _dt.date) -> str:
    return f"{day.month}/{day.day}/{day.year:04d}"


def _value_type(value: MValue) -> MValue:
    return V.TypeValue(V.kind_of(value))


def _value_metadata(value: MValue) -> MValue:
    return value.meta if value.meta is not None else V.Record(())


def _error_record(reason: MValue, message: MValue = V.Null(), detail: MValue = V.Null(),
                  parameters: MValue = V.Null(), code: MValue = V.Null()) -> MValue:
    """Error.Record(reason, message, detail, parameters, errorCode); Message.Format is the message when
    parameters are given (measured)."""
    reason_text = _text(reason)
    message_text = "" if isinstance(message, V.Null) else _text(message)
    if not isinstance(parameters, V.Null) and not isinstance(parameters, V.List):
        raise V.convert_error(parameters, V.TypeValue("list"))
    code_value = V.Null() if isinstance(code, V.Null) else V.Text(_text(code))
    return V.Record((
        ("Reason", V.Text(reason_text)),
        ("Message", V.Text(message_text)),
        ("Detail", detail),
        ("Message.Format", V.Null() if isinstance(parameters, V.Null) else V.Text(message_text)),
        ("Message.Parameters", parameters),
        ("ErrorCode", code_value),
    ))


def _character_to_number(value: MValue) -> MValue:
    """Code point of the first character of the text (an empty text or NUL is a DataFormat.Error)."""
    if isinstance(value, V.Null):
        return V.Null()
    text = _text(value)
    if not text or text[0] == "\x00":
        raise MError("DataFormat.Error", "We couldn't convert to Number.")
    return V.Number(float(ord(text[0])))


def _table_from_records(records: MValue, columns: MValue = V.Null(), missing: MValue = V.Null()) -> MValue:
    """Table.FromRecords: columns are the first record's fields (or the names asked for); every column
    is typed ``any``; a field a later record lacks is an error found only when that cell is read."""
    if not isinstance(records, V.List):
        raise V.convert_error(records, V.TypeValue("list"))
    rows = [V.force(r) for r in records.items]
    if not rows:
        return V.Table((), ())
    for row in rows:
        if not isinstance(row, V.Record):
            raise V.convert_error(row, V.TypeValue("record"))
    if isinstance(columns, V.Null):
        names = list(rows[0].names())
    elif isinstance(columns, V.List):
        names = [_text(V.force(item)) for item in columns.items]
    else:
        raise MError("Expression.Error", "Table.FromRecords: a table type for the columns is not supported yet.")

    def cell(row: V.Record, name: str):
        if row.has(name):
            return row.get(name)
        return V.Thunk(lambda: (_ for _ in ()).throw(MError(
            "Expression.Error", f"The field '{name}' of the record wasn't found.")))

    table_rows = tuple(tuple(cell(row, name) for name in names) for row in rows)
    return V.Table(tuple((name, "any") for name in names), table_rows)


def _list_sum(values: MValue, precision: MValue = V.Null()) -> MValue:
    """List.Sum: null items are skipped; the first other item starts the sum (it must support ``-`` with
    itself, which is why a text, logical, record or list fails with the ``-`` message); further items are
    added with ``+``, numbers only to numbers."""
    from .evaluator import arithmetic  # local import: the evaluator imports this module

    if not isinstance(values, V.List):
        raise V.convert_error(values, V.TypeValue("list"))
    if not isinstance(precision, V.Null):
        if not isinstance(precision, V.Number) or precision.value not in (0.0, 1.0):
            raise MError("Expression.Error", "The value for a 'Precision.Type' enumeration was not one of the "
                         "allowed values: 'Precision.Double, Precision.Decimal'.")
        if precision.value == 1.0:
            raise MError("Expression.Error", "Precision.Decimal sums are not supported by this engine yet.")
    total: MValue = V.Null()
    for item in values.items:
        cell = V.force(item)
        if isinstance(cell, V.Null):
            continue
        if isinstance(total, V.Null):
            arithmetic("-", cell, cell)  # raises the operator error for kinds that cannot be summed
            total = V.Number(cell.value) if isinstance(cell, V.Number) else cell
        elif isinstance(total, V.Number):
            total = V.Number(total.value + _number(cell))
        else:
            total = arithmetic("+", total, cell)
    return total


GLOBALS: dict = {
    "#date": _native((("year", False), ("month", False), ("day", False)), _date),
    "#time": _native((("hour", False), ("minute", False), ("second", False)), _time),
    "#datetime": _native(tuple((n, False) for n in ("year", "month", "day", "hour", "minute", "second")), _datetime),
    "#datetimezone": _native(tuple((n, False) for n in (
        "year", "month", "day", "hour", "minute", "second", "offsetHours", "offsetMinutes")), _datetimezone),
    "#duration": _native((("days", False), ("hours", False), ("minutes", False), ("seconds", False)), _duration),
    "#binary": _native((("list", False),), _binary),
    "Text.Upper": _native((("text", False), ("culture", True)), _text_upper),
    "Text.Length": _native((("text", False),), _text_length),
    "Text.From": _native((("value", False), ("culture", True)), _text_from),
    "Value.Type": _native((("value", False),), _value_type),
    "Value.Metadata": _native((("value", False),), _value_metadata),
    "Error.Record": _native((("reason", False), ("message", True), ("detail", True), ("parameters", True),
                             ("errorCode", True)), _error_record),
    "Character.ToNumber": _native((("character", False),), _character_to_number),
    "Table.FromRecords": _native((("records", False), ("columns", True), ("missingField", True)),
                                 _table_from_records),
    "List.Sum": _native((("list", False), ("precision", True)), _list_sum),
}
