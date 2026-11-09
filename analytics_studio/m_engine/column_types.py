"""Cell conversions of ``Table.TransformColumnTypes`` (Task 111, m-script-101).

A text is first sorted into a *family* by its shape (digits only, a clock time, an ISO date, a number with
separators and so on). Every (family, target type) pair is then one of three outcomes, and nothing else:

- a value, computed from the text by the rule for that family;
- the Power BI error, when the pair was measured with the live oracle (``docs/plans/2026-11-09-m-script-101-probes.json``
  and the spec's engine cases);
- an explicit refusal ("... is not supported by this engine yet."), for every pair that was not measured, and for every
  value that depends on today's date.

A refusal is never turned into a guessed value. Errors are returned as ``MError`` so that the caller can make them
lazy cell errors.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import math
import re
from typing import Optional

from . import values as V
from .canonical import number_text
from .number import NOT_LOGICAL_TEXT, NOT_NUMBER_TEXT, _integer_from, _logical_from, _logical_from_text, _parse_text

# target TypeName -> the base of the value it produces (the Table.Schema TypeNames the engine can build)
BASE_OF_TYPE = {
    "Number.Type": "number", "Int64.Type": "number", "Currency.Type": "number", "Percentage.Type": "number",
    "Text.Type": "text", "Logical.Type": "logical", "Date.Type": "date", "DateTime.Type": "datetime",
    "Time.Type": "time", "Duration.Type": "duration",
}
_CULTURES = {"Number.Type": "de-DE", "Date.Type": "en-GB"}  # the only non-default cultures measured, per target

_DATE_PARSE = "We couldn't parse the input provided as a Date value."
_DATETIME_PARSE = "We couldn't parse the input provided as a DateTime value."
_TIME_PARSE = "We couldn't parse the input provided as a Time value."
_DURATION_PARSE = "We couldn't parse the Duration literal."
_CONVERT = {"date": "We couldn't convert to Date.", "datetime": "We couldn't convert to DateTime.",
            "time": "We couldn't convert to Time.", "duration": "We couldn't convert to Duration.",
            "logical": "We couldn't convert to Logical."}

_TICKS_PER_DAY = V.TICKS_PER_DAY
_SERIAL_EPOCH = _dt.date(1899, 12, 30)  # a number of days is counted from here (measured: 12 is 1900-01-11)
_SERIAL_EPOCH_TICKS = V.date_ticks(_SERIAL_EPOCH)
_MAX_SERIAL_DAYS = (_dt.date(9999, 12, 31) - _SERIAL_EPOCH).days
_MAX_DURATION_DAYS = 10675199  # the days a 64-bit tick count holds

# ---- the family of a source text --------------------------------------------------------------

_MONTHS = {name: i for i, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}
# texts measured as words that no parser reads: letters only, or the hexadecimal-looking "0x10"
_MEASURED_WORDS = frozenset({"abc", "TRUE", "false", "yes", "Infinity", "NaN", "0x10"})

_CLOCK = re.compile(r"([0-9]{1,2}):([0-9]{1,2})(?::([0-9]{1,2})(?:\.([0-9]{1,7}))?)?")
_AMPM = re.compile(r"([0-9]{1,2})(?::([0-9]{1,2})(?::([0-9]{1,2}))?)? ?([AaPp][Mm])")
_DAYS_CLOCK_TEXT = re.compile(r"-?[0-9]+\.[0-9]{2}:[0-9]{2}:[0-9]{2}")
_BAD_SEPARATED = re.compile(r"[-+].*|[.,].*|.*[.,]|.*[.,][.,].*")  # a sign, or an empty group between separators
_BAD_COLON = re.compile(r"[-T]?[0-9]+(:[0-9]*)+")  # colon texts no parser reads: "12:30:", "T12:30", "1:02:03:04"
_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_ISO_DT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?")
_ISO_ANY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ].*")
_MDY = re.compile(r"([A-Za-z]{3}) ([0-9]{1,2}), ([0-9]{4})")
_SLASH = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})")
_DAYS_CLOCK = re.compile(r"(-?[0-9]+)\.([0-9]{2}):([0-9]{2}):([0-9]{2})")
_SIGNED_CLOCK = re.compile(r"(-?)([0-9]{1,2}):([0-9]{1,2})(?::([0-9]{1,2})(?:\.([0-9]{1,7}))?)?")
_NUMISH = re.compile(r"[0-9eE+\-.,$%() x]*")  # what the number reader accepts, and its near misses
_SEPARATED = re.compile(r".*[0-9][.,][0-9].*|.*[0-9][.,]|[.,][0-9].*|[.,]")  # a separator between or next to digits


def _unsupported(what: str) -> V.MError:
    message = f"The {what} is not supported by this engine yet."
    return V.generic_error(message)


def _data_format(message: str) -> V.MError:
    return V.MError("DataFormat.Error", message)


def _expression(message: str) -> V.MError:
    return V.MError("Expression.Error", message)


def _family(s: str) -> str:
    """The family of a trimmed, non-blank text."""
    if s.isascii() and s.isdigit():
        return "DIGITS"
    if _CLOCK.fullmatch(s):
        return "CLOCK"
    if _AMPM.fullmatch(s):
        return "AMPM"
    if _ISO_DATE.fullmatch(s):
        return "ISO_DATE"
    if _ISO_ANY.fullmatch(s):
        return "ISO_DT"
    if _MDY.fullmatch(s):
        return "MDY"
    if _SLASH.fullmatch(s):
        return "SLASH"
    if _DAYS_CLOCK_TEXT.fullmatch(s):
        return "DAYS_CLOCK"
    if _BAD_COLON.fullmatch(s):
        return "BAD_COLON"
    if s in _MEASURED_WORDS:
        return "WORD"
    if _NUMISH.fullmatch(s) and any(ch in "0123456789" for ch in s) or s in ("-", "+", "."):
        return "NUMISH_SEP" if _SEPARATED.fullmatch(s) else "NUMISH"
    return "OTHER"


# ---- clock and calendar pieces ----------------------------------------------------------------

def _calendar(year: int, month: int, day: int) -> Optional[_dt.date]:
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


def _clock_ticks(hour: int, minute: int, second: int, fraction: Optional[str] = None) -> Optional[int]:
    if not (hour < 24 and minute < 60 and second < 60):
        return None
    ticks = (hour * 3600 + minute * 60 + second) * V.TICKS_PER_SECOND
    return ticks + (int(fraction.ljust(7, "0")) if fraction else 0)


def _clock_parts(match: "re.Match") -> Optional[int]:
    """The ticks of a clock text H:M[:S[.f]], or None when a part is out of range."""
    hour, minute, second, fraction = match.groups()
    return _clock_ticks(int(hour), int(minute), int(second or 0), fraction)


def _ampm_ticks(s: str) -> int:
    """The ticks of a 12-hour clock text. Measured: 12 AM is 00, 7 PM is 19, 12 PM stays 12, 13:05 PM stays 13."""
    hour_text, minute, second, marker = _AMPM.fullmatch(s).groups()
    hour = int(hour_text)
    pm = marker.lower() == "pm"
    if hour > 12 and not pm or hour == 0 and pm:
        raise _unsupported("12-hour time text with this hour")
    if pm and hour < 12:
        hour += 12
    elif not pm and hour == 12:
        hour = 0
    ticks = _clock_ticks(hour, int(minute or 0), int(second or 0))
    if ticks is None:
        raise _unsupported("12-hour time text out of range")
    return ticks


# ---- text to each target ----------------------------------------------------------------------

def _text_to_number(s: str, type_name: str, culture: str) -> V.MValue:
    number = _parse_text(s, culture)
    if number is None:
        raise _data_format(NOT_NUMBER_TEXT)  # measured for every text the number reader refuses
    return _number_target(number, type_name)


def _number_target(number: V.Number, type_name: str) -> V.MValue:
    x = number.value
    if type_name == "Int64.Type":
        return _integer_from("a 64 bit integer value", V.INT64_MIN, V.INT64_MAX, False)(number)  # ties to even
    if type_name in ("Currency.Type", "Percentage.Type"):
        if math.isnan(x):
            raise V.MError("Expression.Error", "The number is out of range of a decimal value.")
        exact = math.isfinite(x) and abs(x) < 1e15 and float("%.15g" % x) == x
        if not exact or type_name == "Currency.Type" and round(x, 4) != x:
            raise _unsupported("number as this column type")  # fixed-decimal rounding and range are not measured
    return number


def _text_to_date(s: str, padded: bool, culture: str) -> V.MValue:
    family = _family(s)
    if family in ("CLOCK", "AMPM", "ISO_DT", "BAD_COLON", "DAYS_CLOCK", "WORD", "NUMISH"):
        raise _data_format(_DATE_PARSE)
    if family == "NUMISH_SEP" and _BAD_SEPARATED.fullmatch(s):
        raise _data_format(_DATE_PARSE)  # measured: "-3.5", "-1,000.5", "5.", ".5", "."
    if family == "DIGITS":
        if len(s) == 4 and int(s) >= 1 and not padded:
            return V.make_date_from_ticks(V.date_ticks(_dt.date(int(s), 1, 1)))  # measured: a year alone
        if len(s) != 4 or int(s) == 0:
            raise _data_format(_DATE_PARSE)
        raise _unsupported("padded year text as a date")
    if padded:
        raise _unsupported("padded date text")
    if family == "ISO_DATE":
        day = _calendar(*(int(part) for part in s.split("-")))
        if day is None:
            raise _unsupported("date text that is not a calendar date")
        return V.make_date_from_ticks(V.date_ticks(day))
    if family == "MDY":
        month_name, day_text, year = _MDY.fullmatch(s).groups()
        day = _calendar(int(year), _MONTHS.get(month_name, 0), int(day_text))
        if day is None:
            raise _unsupported("date text that is not a calendar date")
        return V.make_date_from_ticks(V.date_ticks(day))
    if family == "SLASH":
        first, second, year = (int(part) for part in s.split("/"))
        if culture == "en-GB":
            day = _calendar(year, second, first)
            if day is None:
                raise _unsupported("date text that is not a calendar date")
            return V.make_date_from_ticks(V.date_ticks(day))
        if first > 12:
            raise _data_format(_DATE_PARSE)  # measured: 29/02/2024 is no month/day/year date
    raise _unsupported("text as a date")


def _text_to_datetime(s: str, padded: bool) -> V.MValue:
    family = _family(s)
    if family in ("DIGITS", "NUMISH", "WORD", "BAD_COLON", "DAYS_CLOCK"):
        raise _data_format(_DATETIME_PARSE)
    if family == "NUMISH_SEP" and _BAD_SEPARATED.fullmatch(s):
        raise _data_format(_DATETIME_PARSE)
    if family == "CLOCK" and _clock_parts(_CLOCK.fullmatch(s)) is None:
        raise _data_format(_DATETIME_PARSE)  # measured: 24:00, 23:60, 25:00, 12:30:60
    if family in ("CLOCK", "AMPM"):
        raise _unsupported("time text as a DateTime")  # it is today's date: not a fixed value
    if padded:
        raise _unsupported("padded date text")
    if family == "ISO_DATE":
        day = _calendar(*(int(part) for part in s.split("-")))
        if day is None:
            raise _unsupported("date text that is not a calendar date")
        return V.DateTime(V.date_ticks(day))
    if family == "MDY":
        month_name, day_text, year = _MDY.fullmatch(s).groups()
        day = _calendar(int(year), _MONTHS.get(month_name, 0), int(day_text))
        if day is None:
            raise _unsupported("date text that is not a calendar date")
        return V.DateTime(V.date_ticks(day))
    if family == "ISO_DT":
        match = _ISO_DT.fullmatch(s)
        if match is None:
            raise _unsupported("date and time text of this shape")
        year, month, day_number, hour, minute, second = match.groups()
        day = _calendar(int(year), int(month), int(day_number))
        clock = _clock_ticks(int(hour), int(minute), int(second or 0))
        if day is None or clock is None:
            raise _unsupported("date and time text out of range")
        return V.DateTime(V.date_ticks(day) + clock)
    if family == "SLASH" and int(s.split("/")[0]) > 12:
        raise _data_format(_DATETIME_PARSE)
    raise _unsupported("text as a DateTime")


def _text_to_time(s: str, padded: bool) -> V.MValue:
    family = _family(s)
    if family == "CLOCK":
        ticks = _clock_parts(_CLOCK.fullmatch(s))
        if ticks is None:
            raise _expression(_TIME_PARSE)
        return V.make_time(ticks)
    if family == "AMPM":
        if padded:
            raise _unsupported("padded 12-hour time text")
        return V.make_time(_ampm_ticks(s))
    if family == "DIGITS":
        # measured: two digits are the hour, four are hour and minute; one, three or five digits are no time
        if len(s) in (1, 3, 5):
            raise _expression(_TIME_PARSE)
        if padded:
            raise _unsupported("padded digits as a time")
        if len(s) == 2:
            ticks = _clock_ticks(int(s), 0, 0)
        elif len(s) == 4:
            ticks = _clock_ticks(int(s[:2]), int(s[2:]), 0)
        else:
            raise _unsupported("digits as a time")
        if ticks is None:
            if len(s) == 4 and int(s[:2]) > 23:
                raise _unsupported("digits as a time")
            raise _expression(_TIME_PARSE)
        return V.make_time(ticks)
    if family in ("ISO_DATE", "ISO_DT", "MDY", "SLASH", "BAD_COLON", "DAYS_CLOCK", "WORD", "NUMISH", "NUMISH_SEP"):
        raise _expression(_TIME_PARSE)
    raise _unsupported("text as a Time")


def _text_to_duration(s: str) -> V.MValue:
    family = _family(s)
    if family == "DIGITS" or re.fullmatch(r"-[0-9]+", s):
        days = int(s)
        if abs(days) > _MAX_DURATION_DAYS:
            raise _unsupported("duration beyond the largest day count")
        return V.make_duration(days * _TICKS_PER_DAY)  # measured: a whole number is a count of days
    if family == "CLOCK" or _SIGNED_CLOCK.fullmatch(s):
        match = _SIGNED_CLOCK.fullmatch(s)
        sign, hour, minute, second, fraction = match.groups()
        ticks = _clock_ticks(int(hour), int(minute), int(second or 0), fraction)
        if ticks is None:
            raise _expression(_DURATION_PARSE)
        return V.make_duration(-ticks if sign else ticks)
    match = _DAYS_CLOCK.fullmatch(s)
    if match is not None:
        days, hour, minute, second = match.groups()
        ticks = _clock_ticks(int(hour), int(minute), int(second))
        if ticks is None or days.startswith("-"):
            raise _unsupported("duration text of this shape")
        return V.make_duration(int(days) * _TICKS_PER_DAY + ticks)
    if family in ("AMPM", "ISO_DATE", "ISO_DT", "MDY", "SLASH", "BAD_COLON", "WORD", "NUMISH", "NUMISH_SEP"):
        raise _expression(_DURATION_PARSE)
    if ":" in s and re.fullmatch(r"[0-9:. \-TAPMapm]+", s):
        raise _expression(_DURATION_PARSE)  # measured: "12 : 30" and other colon texts that are no literal
    raise _unsupported("text as a Duration")


def _text_to_logical(s: str, padded: bool) -> V.MValue:
    if s.lower() in ("true", "false"):
        if padded:
            raise _unsupported("padded text as a logical")
        return _logical_from_text(V.Text(s))
    if _family(s) == "OTHER":
        raise _unsupported("text as a logical")
    raise V.MError("Expression.Error", NOT_LOGICAL_TEXT)  # measured for numbers, dates, times and words


def _convert_text(text: str, type_name: str, base: str, culture: Optional[str]) -> V.MValue:
    if base == "text":
        if culture is not None:
            raise _unsupported("culture argument")
        return V.Text(text)  # measured: text stays text, blank or not
    if text.strip(" ") == "":
        if culture is not None:
            raise _unsupported("culture argument")
        return V.Null()  # measured: empty and space-only text is null for every other type
    s = text.strip(" \t")
    if s == "":
        raise _unsupported("blank text of this kind")
    padded = s != text
    if culture is not None and _CULTURES.get(type_name) != culture:
        raise _unsupported("culture argument")
    use = culture or "en-US"
    if base == "number":
        return _text_to_number(s, type_name, use)
    if base == "date":
        return _text_to_date(s, padded, use)
    if base == "datetime":
        return _text_to_datetime(s, padded)
    if base == "time":
        return _text_to_time(s, padded)
    if base == "duration":
        return _text_to_duration(s)
    return _text_to_logical(s, padded)


# ---- other sources ----------------------------------------------------------------------------

def _serial_days(value: V.Date) -> int:
    return (V.date_ticks(value.value) - _SERIAL_EPOCH_TICKS) // _TICKS_PER_DAY


def _number_to_date(value: V.Number) -> V.MValue:
    x = value.value
    if not math.isfinite(x) or x < 0 or x >= _MAX_SERIAL_DAYS + 1:
        raise _unsupported("number as a date")
    return V.make_date_from_ticks(_SERIAL_EPOCH_TICKS + math.floor(x) * _TICKS_PER_DAY)  # measured: 12, 1.5


def _number_to_duration(value: V.Number) -> V.MValue:
    x = value.value
    if not math.isfinite(x) or x < 0 or x > _MAX_DURATION_DAYS:
        raise _unsupported("number as a Duration")
    with _decimal.localcontext() as context:
        context.prec = 50
        ticks = (_decimal.Decimal(repr(x)) * _TICKS_PER_DAY).to_integral_value(_decimal.ROUND_HALF_EVEN)
    return V.make_duration(int(ticks))  # measured: a count of days, 12 and 1.5


def _number_to_time(value: V.Number) -> V.MValue:
    if math.isfinite(value.value) and value.value >= 1:
        raise _data_format(_CONVERT["time"])  # a whole day or more is no time of day (measured for 12 and 1.5)
    raise _unsupported("number as a Time")


def _number_to_datetime(value: V.Number) -> V.MValue:
    if not math.isfinite(value.value) or value.value < 0:
        raise _unsupported("number as a DateTime")
    from .date_fns import _date_time_from  # local import: date_fns is loaded after this module

    return _date_time_from(value)


def _number_source(value: V.Number, base: str, type_name: str) -> V.MValue:
    if base == "text":
        return V.Text(number_text(value.value))
    if base == "number":
        return _number_target(value, type_name)
    if base == "logical":
        return _logical_from(value)
    if base == "date":
        return _number_to_date(value)
    if base == "datetime":
        return _number_to_datetime(value)
    if base == "time":
        return _number_to_time(value)
    return _number_to_duration(value)


def _logical_source(value: V.Logical, base: str, type_name: str) -> V.MValue:
    if base == "logical":
        return value
    if base == "text":
        return V.Text("true" if value.value else "false")
    if base == "number":
        return _number_target(V.Number(1.0 if value.value else 0.0), type_name)
    raise _data_format(_CONVERT[base])  # measured for true: no date, datetime, time or duration


def _date_source(value: V.Date, base: str, type_name: str) -> V.MValue:
    if base == "date":
        return value
    if base == "datetime":
        return V.DateTime(V.date_ticks(value.value))
    if base == "number":
        return _number_target(V.Number(float(_serial_days(value))), type_name)
    if base == "text":
        if value.value.year < 1000:
            raise _unsupported("date value below the year 1000 as text")
        return V.Text(f"{value.value.month}/{value.value.day}/{value.value.year}")  # measured: 1/2/2024
    raise _data_format(_CONVERT[base])  # measured: no time, logical or duration


def convert_cell(value: V.MValue, type_name: str, culture: Optional[str] = None) -> V.MValue:
    """The value of one cell after its column is converted to ``type_name``. Raises MError for Power BI's error and
    for every case that is not measured (the engine's explicit refusal)."""
    if type_name not in BASE_OF_TYPE:
        raise _unsupported("column type " + type_name)
    if isinstance(value, V.Null):
        return value
    base = BASE_OF_TYPE[type_name]
    if isinstance(value, V.Text):
        return _convert_text(value.value, type_name, base, culture)
    if culture is not None:
        raise _unsupported("culture argument")  # a culture is only measured for text sources
    if isinstance(value, V.Number):
        return _number_source(value, base, type_name)
    if isinstance(value, V.Logical):
        return _logical_source(value, base, type_name)
    if isinstance(value, V.Date):
        return _date_source(value, base, type_name)
    raise _unsupported(f"{V.type_display(value)} value as {type_name}")
