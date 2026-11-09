"""Power Query ``Date.*``, ``DateTime.*``, ``DateTimeZone.*``, ``Time.*`` and ``Duration.*`` functions and the ``Day.*``
constants (Task 106, m-date-96).

Every answer is computed from the arguments: calendar arithmetic on day ordinals, wall-clock ticks and offsets,
.NET-style standard and custom format strings for the cultures in ``_CULTURES``, and the text parsers below. Nothing is
looked up.

Refused, never guessed (an explicit ERR): anything that reads the clock (``LocalNow``, ``UtcNow``, ...), anything that
depends on the machine's time zone (``DateTime.From`` of a DateTimeZone, ``DateTimeZone.FromText`` and
``DateTimeZone.From`` without an offset, a time alone read as a DateTime), cultures and format specifiers this module
has no rules for, and every input whose Power BI answer has not been measured.

Messages are copied from measured answers; a pattern is generalised only where the measured answers show the pattern.
"""

from __future__ import annotations

import calendar
import datetime as _dt
import math
import re
from dataclasses import dataclass
from typing import Optional

from . import values as V
from .values import MError, MValue

TPS = V.TICKS_PER_SECOND
TPM = V.TICKS_PER_MINUTE
TPH = V.TICKS_PER_HOUR
TPD = V.TICKS_PER_DAY


# ---- helpers ---------------------------------------------------------------

def _native(params: tuple, fn) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke)


def _unsupported(what: str) -> MError:
    """Not a Power BI answer this engine has measured: an explicit ERR, never a guessed value."""
    return V.generic_error(f"The {what} is not supported by this engine yet.")


class _Invalid(Exception):
    """The text is not in the form the function reads: Power BI's parse error for the kind."""


class _Refuse(Exception):
    """A text whose Power BI answer depends on the clock, the machine's zone or a form not measured."""


def _num(x) -> V.Number:
    return V.Number(float(x))


def _whole(value: MValue, what: str) -> int:
    """An integral Number argument (the day, month or hour counts); anything else is refused."""
    if isinstance(value, V.Number) and math.isfinite(value.value) and value.value == int(value.value):
        return int(value.value)
    raise _unsupported(f"{what} argument that is not a whole number")


def _first_day(value: MValue) -> int:
    """firstDayOfWeek: Day.Sunday (0) when omitted or null; Day.Monday is 1 and so on."""
    if isinstance(value, V.Null):
        return 0
    number = _whole(value, "firstDayOfWeek")
    if 0 <= number <= 6:
        return number
    raise _unsupported("firstDayOfWeek outside Day.Sunday to Day.Saturday")


def _net_dow(day: _dt.date) -> int:
    """.NET DayOfWeek: Sunday is 0."""
    return (day.weekday() + 1) % 7


def _day_ticks(ordinal: int) -> int:
    return (ordinal - 1) * TPD


def _range(kind: str) -> MError:
    return V.range_error(kind)


# ---- cultures ----------------------------------------------------------------

@dataclass(frozen=True)
class _Culture:
    name: str
    months: tuple
    abbr_months: Optional[tuple]
    days: Optional[tuple]  # Sunday first, as .NET DayOfWeek
    abbr_days: Optional[tuple]
    date_sep: str
    am: Optional[str]
    pm: Optional[str]
    short_date: Optional[str]  # standard "d"
    long_date: Optional[str]  # standard "D"
    general: Optional[str]  # standard "G" (date and time)
    short_time: Optional[str]  # standard "t"
    numeric_order: Optional[str]  # order of a slash date when parsing: "MDY" or "DMY"


_EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December")
_EN_ABBR_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_EN_DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
_EN_ABBR_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
_DE_MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
              "November", "Dezember")
_DE_DAYS = ("Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag")
_FR_MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
              "novembre", "décembre")

_CULTURES = {
    "en-us": _Culture("en-us", _EN_MONTHS, _EN_ABBR_MONTHS, _EN_DAYS, _EN_ABBR_DAYS, "/", "AM", "PM",
                      "M/d/yyyy", "dddd, MMMM d, yyyy", "M/d/yyyy h:mm:ss tt", "h:mm tt", "MDY"),
    "en-gb": _Culture("en-gb", _EN_MONTHS, _EN_ABBR_MONTHS, _EN_DAYS, _EN_ABBR_DAYS, "/", None, None,
                      None, None, None, None, "DMY"),
    "de-de": _Culture("de-de", _DE_MONTHS, None, _DE_DAYS, None, ".", None, None,
                      None, "dddd, d. MMMM yyyy", None, None, None),
    "fr-fr": _Culture("fr-fr", _FR_MONTHS, None, None, None, "/", None, None,
                      None, None, None, None, None),
}


def _culture(name: MValue) -> _Culture:
    """The culture of a text argument; null is the current culture, en-US."""
    if isinstance(name, V.Null):
        return _CULTURES["en-us"]
    if not isinstance(name, V.Text):
        raise _unsupported("culture that is not text")
    key = name.value.lower() or "en-us"
    culture = _CULTURES.get(key)
    if culture is None:
        from .stdlib import _unsupported_culture  # local import: stdlib registers this module

        raise _unsupported_culture(name.value)
    return culture


# ---- the moments: Date, DateTime, DateTimeZone, Time -------------------------

@dataclass(frozen=True)
class _When:
    kind: str  # "date", "datetime", "datetimezone" or "time"
    wall: int  # wall-clock ticks since 0001-01-01 (for a time: ticks into the day)
    offset: int = 0  # minutes east of UTC (datetimezone only)


DATE_ARG = ("date", "datetime", "datetimezone")
TIME_ARG = ("time", "datetime", "datetimezone")


def _when(value: MValue, accept: tuple, convert_from: tuple = (), convert_to: Optional[str] = None,
          text_is_date: bool = False) -> Optional[_When]:
    """The moment behind a value: None for null. A kind named in ``convert_from`` raises the measured conversion
    error to ``convert_to``; a text argument of a date function raises the measured date-component message."""
    if isinstance(value, V.Null):
        return None
    kind = V.kind_of(value)
    if kind in accept:
        if kind == "date":
            return _When(kind, V.date_ticks(value.value))
        if kind == "datetimezone":
            return _When(kind, value.ticks, value.offset_minutes)
        return _When(kind, value.ticks)
    if convert_to is not None and kind in convert_from:
        raise V.convert_error(value, V.TypeValue(convert_to))
    if text_is_date and kind == "text":
        raise MError("Expression.Error", "The Date value must contain the Date component.",
                     fmt="The Date value must contain the Date component.")
    raise _unsupported(f"{V.type_display(value)} value")


def _day(w: _When) -> _dt.date:
    return V.ticks_to_date(w.wall - w.wall % TPD)


def _result(kind: str, wall: int, offset: int = 0) -> MValue:
    """Build a value of ``kind`` from wall-clock ticks, checking the range the way Power BI reports it."""
    if kind == "date":
        if not 0 <= wall <= V.MAX_DATETIME_TICKS or wall % TPD:
            raise _range("Date")
        return V.Date(V.ticks_to_date(wall))
    if kind == "datetime":
        return V.make_datetime(wall)
    if kind == "datetimezone":
        return V.make_datetimezone(wall, offset)
    if not 0 <= wall < TPD:
        raise _range("Time")
    return V.Time(wall)


def _with_day(w: _When, day_ordinal: int, tod: int) -> MValue:
    return _result(w.kind, _day_ticks(day_ordinal) + tod, w.offset)


def _at(w: _When, ordinal: int, last: bool) -> MValue:
    """The start (or, with ``last``, the end) of a day: a Date keeps no time; a DateTime or DateTimeZone runs to
    23:59:59.9999999 at the end."""
    ticks = _day_ticks(ordinal)
    if last and w.kind != "date":
        ticks += TPD - 1
    return _result(w.kind, ticks, w.offset)


def _ordinal(w: _When) -> int:
    return w.wall // TPD + 1


def _ymd(w: _When) -> tuple:
    day = _day(w)
    return day.year, day.month, day.day


# ---- Date -----------------------------------------------------------------

def _date_component(getter):
    def invoke(value: MValue) -> MValue:
        w = _when(value, DATE_ARG, text_is_date=True)
        return V.Null() if w is None else getter(w)

    return invoke


def _year(w): return _num(_day(w).year)


def _month(w): return _num(_day(w).month)


def _day_of_month(w): return _num(_day(w).day)


def _day_of_year(w): return _num(_day(w).timetuple().tm_yday)


def _days_in_month(w):
    y, m, _ = _ymd(w)
    return _num(calendar.monthrange(y, m)[1])


def _quarter(w): return _num((_day(w).month - 1) // 3 + 1)


def _is_leap(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Number):
        if not math.isfinite(value.value):
            raise _unsupported("non-finite number as a year")
        return V.Logical(calendar.isleap(int(value.value)))
    w = _when(value, DATE_ARG, text_is_date=True)
    return V.Null() if w is None else V.Logical(calendar.isleap(_day(w).year))


def _day_of_week(value: MValue, first: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    return _num((_net_dow(_day(w)) - _first_day(first)) % 7)


def _week_of_month(value: MValue, first: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    day = _day(w)
    start = day.replace(day=1)
    offset = (_net_dow(start) - _first_day(first)) % 7
    return _num((day.day - 1 + offset) // 7 + 1)


def _week_of_year(value: MValue, first: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    day = _day(w)
    jan1 = _dt.date(day.year, 1, 1)
    offset = (_net_dow(jan1) - _first_day(first)) % 7
    return _num((day.timetuple().tm_yday - 1 + offset) // 7 + 1)


def _start_of_week(value: MValue, first: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    day = _day(w)
    start = _ordinal(w) - (_net_dow(day) - _first_day(first)) % 7
    return _at(w, start, last=False)


def _end_of_week(value: MValue, first: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    day = _day(w)
    start = _ordinal(w) - (_net_dow(day) - _first_day(first)) % 7
    return _at(w, start + 6, last=True)


def _start_of_day(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    return V.Null() if w is None else _at(w, _ordinal(w), last=False)


def _end_of_day(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    return V.Null() if w is None else _at(w, _ordinal(w), last=True)


def _start_of_month(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    y, m, _ = _ymd(w)
    return _at(w, _dt.date(y, m, 1).toordinal(), last=False)


def _end_of_month(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    y, m, _ = _ymd(w)
    return _at(w, _dt.date(y, m, calendar.monthrange(y, m)[1]).toordinal(), last=True)


def _start_of_quarter(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    y, m, _ = _ymd(w)
    first_month = (m - 1) // 3 * 3 + 1
    return _at(w, _dt.date(y, first_month, 1).toordinal(), last=False)


def _end_of_quarter(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    y, m, _ = _ymd(w)
    last_month = (m - 1) // 3 * 3 + 3
    return _at(w, _dt.date(y, last_month, calendar.monthrange(y, last_month)[1]).toordinal(), last=True)


def _start_of_year(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    return V.Null() if w is None else _at(w, _dt.date(_ymd(w)[0], 1, 1).toordinal(), last=False)


def _end_of_year(value: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    return V.Null() if w is None else _at(w, _dt.date(_ymd(w)[0], 12, 31).toordinal(), last=True)


def _add_days(value: MValue, count: MValue) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    return _result(w.kind, w.wall + _whole(count, "day count") * TPD, w.offset)


def _add_months(w: _When, months: int) -> MValue:
    y, m, d = _ymd(w)
    total = y * 12 + (m - 1) + months
    new_year, new_month = total // 12, total % 12 + 1
    if not 1 <= new_year <= 9999:
        raise _range(_kind_name(w.kind))
    new_day = min(d, calendar.monthrange(new_year, new_month)[1])
    tod = w.wall % TPD
    return _result(w.kind, V.date_ticks(_dt.date(new_year, new_month, new_day)) + tod, w.offset)


def _kind_name(kind: str) -> str:
    return {"date": "Date", "datetime": "DateTime", "datetimezone": "DateTimeZone", "time": "Time"}[kind]


def _add_month_count(value: MValue, count: MValue, factor: int) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    return _add_months(w, _whole(count, "month count") * factor)


def _month_name(value: MValue, culture: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    text_culture = _culture(culture)
    if w.kind == "date" and w.wall == 0:  # measured: the first day of year 1 has no local time (positive zones)
        raise MError("DataFormat.Error", "We couldn't convert to DateTimeZone.")
    if text_culture.months is None:
        raise _unsupported("month name in this culture")
    return V.Text(text_culture.months[_day(w).month - 1])


def _day_of_week_name(value: MValue, culture: MValue = V.Null()) -> MValue:
    w = _when(value, DATE_ARG, text_is_date=True)
    if w is None:
        return V.Null()
    text_culture = _culture(culture)
    if w.kind == "date" and w.wall == 0:  # measured, as for MonthName
        raise MError("DataFormat.Error", "We couldn't convert to DateTimeZone.")
    if text_culture.days is None:
        raise _unsupported("day name in this culture")
    return V.Text(text_culture.days[_net_dow(_day(w))])


def _date_to_record(value: MValue) -> MValue:
    w = _when(value, ("date",), convert_from=("datetime", "datetimezone"), convert_to="date")
    if w is None:
        return V.Null()
    y, m, d = _ymd(w)
    return V.Record((("Year", _num(y)), ("Month", _num(m)), ("Day", _num(d))))


# ---- formatting ------------------------------------------------------------

_CUSTOM_LETTERS = "yMdhHmstfz"


def _standard_pattern(letter: str, culture: _Culture, kind: str) -> str:
    """A one-letter format is a standard format: only the measured or unambiguous ones are expanded."""
    if letter == "d" and kind in ("date", "datetime", "datetimezone") and culture.short_date:
        return culture.short_date
    if letter == "D" and kind in ("date", "datetime") and culture.long_date:
        return culture.long_date
    if letter == "G" and kind in ("datetime", "datetimezone") and culture.general:
        return culture.general
    if letter == "t" and kind == "time" and culture.short_time:
        return culture.short_time
    raise _unsupported(f"standard format {letter}")


def _default_pattern(culture: _Culture, kind: str) -> str:
    if kind == "date":
        pattern = culture.short_date
    elif kind == "datetime":
        pattern = culture.general
    elif kind == "datetimezone":
        pattern = None if culture.general is None else culture.general + " zzz"
    else:
        pattern = culture.short_time
    if pattern is None:
        raise _unsupported("default format in this culture")
    return pattern


def _field(ch: str, count: int, w: _When, culture: _Culture) -> str:
    kind = w.kind
    if ch in "yMd":
        if kind == "time":
            raise _unsupported("date field in a time format")
        day = _day(w)
        if ch == "y":
            if count > 5:
                raise _unsupported("year format")
            if count == 1:
                return str(day.year % 100)
            if count == 2:
                return f"{day.year % 100:02d}"
            return f"{day.year:0{count}d}"
        if ch == "M":
            if count == 1:
                return str(day.month)
            if count == 2:
                return f"{day.month:02d}"
            if count == 3 and culture.abbr_months:
                return culture.abbr_months[day.month - 1]
            if count == 4:
                return culture.months[day.month - 1]
            raise _unsupported("month format")
        net = _net_dow(day)
        if count == 1:
            return str(day.day)
        if count == 2:
            return f"{day.day:02d}"
        if count == 3 and culture.abbr_days:
            return culture.abbr_days[net]
        if count == 4 and culture.days:
            return culture.days[net]
        raise _unsupported("day format")
    if kind == "date":
        raise _unsupported("time field in a date format")
    hour = (w.wall % TPD) // TPH
    minute = (w.wall % TPH) // TPM
    second = (w.wall % TPM) // TPS
    fraction = w.wall % TPS
    if ch in "hH":
        if count > 2:
            raise _unsupported("hour format")
        shown = (hour % 12 or 12) if ch == "h" else hour
        return str(shown) if count == 1 else f"{shown:02d}"
    if ch == "m":
        if count > 2:
            raise _unsupported("minute format")
        return str(minute) if count == 1 else f"{minute:02d}"
    if ch == "s":
        if count > 2:
            raise _unsupported("second format")
        return str(second) if count == 1 else f"{second:02d}"
    if ch == "f":
        if count > 7:
            raise _unsupported("fraction format")
        return f"{fraction:07d}"[:count]
    if ch == "t":
        if count > 2 or culture.am is None:
            raise _unsupported("AM/PM format")
        marker = culture.am if hour < 12 else culture.pm
        return marker if count == 2 else marker[0]
    # ch == "z": the offset of a DateTimeZone
    if kind != "datetimezone" or count > 3:
        raise _unsupported("offset format")
    sign = "+" if w.offset >= 0 else "-"
    hours, minutes = divmod(abs(w.offset), 60)
    if count == 1:
        return f"{sign}{hours}"
    if count == 2:
        return f"{sign}{hours:02d}"
    return f"{sign}{hours:02d}:{minutes:02d}"


def _custom(pattern: str, culture: _Culture, w: _When) -> str:
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch in "'\"\\%":
            raise _unsupported("format specifier")
        if ch == "/":
            out.append(culture.date_sep)
            i += 1
        elif ch == ":":
            out.append(":")
            i += 1
        elif ch in _CUSTOM_LETTERS:
            j = i
            while j < len(pattern) and pattern[j] == ch:
                j += 1
            out.append(_field(ch, j - i, w, culture))
            i = j
        elif ch == "T":  # not a .NET format character: copied as a literal
            out.append("T")
            i += 1
        elif ch.isalpha():
            raise _unsupported("format specifier")
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _format(w: _When, fmt: Optional[str], culture: _Culture) -> str:
    if fmt is None:
        pattern = _default_pattern(culture, w.kind)
    elif len(fmt) == 1:
        pattern = _standard_pattern(fmt, culture, w.kind)
    else:
        pattern = fmt
    return _custom(pattern, culture, w)


def _text_option(value: MValue) -> Optional[str]:
    if isinstance(value, V.Null):
        return None
    if isinstance(value, V.Text):
        return value.value
    raise _unsupported("format that is not text")


def _format_options(value: MValue) -> tuple:
    """(format, culture) from a format argument: null, a text (the format) or a record [Format, Culture]."""
    if isinstance(value, V.Null):
        return None, V.Null()
    if isinstance(value, V.Text):
        return value.value, V.Null()
    if not isinstance(value, V.Record):
        raise _unsupported("format argument")
    for name in value.names():
        if name not in ("Format", "Culture"):
            raise _unsupported("format option")
    fmt = value.get("Format")
    culture = value.get("Culture")
    return _text_option(fmt if fmt is not None else V.Null()), culture if culture is not None else V.Null()


def _date_to_text(value: MValue, options: MValue = V.Null()) -> MValue:
    w = _when(value, ("date",), convert_from=("datetime", "datetimezone"), convert_to="date")
    if w is None:
        return V.Null()
    fmt, culture = _format_options(options)
    return V.Text(_format(w, fmt, _culture(culture)))


# ---- parsing --------------------------------------------------------------

_ISO_DATE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
_SLASH_DATE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
_DOT_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{1,2}|\d{4})")
_NAMED_DATE = re.compile(r"([A-Za-z]+)\.? (\d{1,2}),? (\d{4})")
_NAMED_DATE_DAY_FIRST = re.compile(r"(\d{1,2}) ([A-Za-z]+)\.? (\d{4})")
_TIME_ONLY = re.compile(r"(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.(\d{1,7}))?)?")
_TIME_12H = re.compile(r"(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.(\d{1,7}))?)?\s*([AP]M|[ap]m)")
_TIME_TAIL = re.compile(r"[T ](\d{1,2}:\d{1,2}(?::\d{1,2}(?:\.\d{1,7})?)?)\s*(Z|[+-]\d{2}:\d{2})?")
_OFFSET = re.compile(r"([+-])(\d{2}):(\d{2})")
_DURATION_CLOCK = re.compile(r"(-)?(?:(\d+)\.)?(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,7}))?)?")
_DURATION_ISO = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)(?:\.(\d{1,7}))?S)?)?")
_MONTH_BY_NAME = {name.lower(): index + 1 for index, name in enumerate(_EN_MONTHS)}
_MONTH_BY_NAME.update({name.lower(): index + 1 for index, name in enumerate(_EN_ABBR_MONTHS)})


@dataclass(frozen=True)
class _Parsed:
    day: Optional[_dt.date]  # None: a time of day alone
    tod: Optional[int]  # ticks into the day when the text has a time
    offset: Optional[int]  # minutes when the text has an offset


def _make_day(year: int, month: int, day: int) -> _dt.date:
    try:
        return _dt.date(year, month, day)
    except ValueError:
        raise _Invalid()


def _time_ticks(match: re.Match) -> int:
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    fraction = int((match.group(4) or "").ljust(7, "0") or 0)
    if hour > 23 or minute > 59 or second > 59:
        raise _Refuse()  # the range rule for a time text is not measured
    return hour * TPH + minute * TPM + second * TPS + fraction


def _offset_minutes(text: str) -> int:
    if text == "Z":
        return 0
    match = _OFFSET.fullmatch(text)
    hours, minutes = int(match.group(2)), int(match.group(3))
    if hours > 14 or minutes > 59:
        raise _Refuse()
    total = hours * 60 + minutes
    return -total if match.group(1) == "-" else total


def _date_head(head: str, culture: _Culture) -> Optional[_dt.date]:
    match = _ISO_DATE.fullmatch(head)
    if match:
        return _make_day(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = _SLASH_DATE.fullmatch(head)
    if match:
        if culture.numeric_order is None:
            raise _Refuse()
        a, b, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        month, day = (a, b) if culture.numeric_order == "MDY" else (b, a)
        return _make_day(year, month, day)
    match = _DOT_DATE.fullmatch(head)
    if match:
        a, b, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        year = (2000 + y) if y < 100 else y
        month, day = (a, b) if (culture.numeric_order or "MDY") == "MDY" else (b, a)
        return _make_day(year, month, day)
    match = _NAMED_DATE.fullmatch(head)
    if match:
        if culture.name != "en-us":
            raise _Refuse()
        month = _MONTH_BY_NAME.get(match.group(1).lower())
        if month is None:
            raise _Refuse()  # an English month name outside the full and three-letter names: not measured
        return _make_day(int(match.group(3)), month, int(match.group(2)))
    match = _NAMED_DATE_DAY_FIRST.fullmatch(head)
    if match:
        if culture.name != "en-us":
            raise _Refuse()
        month = _MONTH_BY_NAME.get(match.group(2).lower())
        if month is None:
            raise _Refuse()
        return _make_day(int(match.group(3)), month, int(match.group(1)))
    return None


def _parse(text: str, culture: _Culture) -> _Parsed:
    if text != text.strip():
        raise _Refuse()
    m12 = _TIME_12H.fullmatch(text)
    if m12:
        hour, minute = int(m12.group(1)), int(m12.group(2))
        second = int(m12.group(3) or 0)
        fraction = int((m12.group(4) or "").ljust(7, "0") or 0)
        meridiem = m12.group(5).upper()
        if not (1 <= hour <= 12 and 0 <= minute <= 59 and 0 <= second <= 59):
            raise _Refuse()
        if meridiem == "AM":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
        return _Parsed(None, hour * TPH + minute * TPM + second * TPS + fraction, None)
    if re.search(r"\b(AM|PM|am|pm)\b", text):
        raise _Refuse()
    if re.fullmatch(r"\d{1,2}:\d{1,2}(?::\d{1,2}(?:\.\d+)?)?", text) and not _TIME_ONLY.fullmatch(text):
        raise _Refuse()  # a clock-shaped text outside the measured grammar (one-digit minutes, long fractions)
    tail = _TIME_TAIL.search(text)
    head = text[:tail.start()] if tail else text
    tod = _time_ticks(_TIME_ONLY.fullmatch(tail.group(1))) if tail else None
    offset = (_offset_minutes(tail.group(2)) if tail.group(2) else None) if tail else None
    if tail is None and _TIME_ONLY.fullmatch(text):
        return _Parsed(None, _time_ticks(_TIME_ONLY.fullmatch(text)), None)
    day = _date_head(head, culture) if head else None
    if day is None:
        if re.search(r"\d{4}", text):
            raise _Refuse()  # a year is there but the form is not one this module reads
        raise _Invalid()
    return _Parsed(day, tod, offset)


_FORMAT_TOKEN = re.compile(r"yyyy|MM|M|dd|d|[-/. ,]")


def _date_from_format(text: str, fmt: str, culture: _Culture) -> _dt.date:
    """Date.FromText with a numeric custom format (yyyy, MM, M, dd, d and the separators - / . space comma)."""
    parts = []
    seen = set()
    pos = 0
    while pos < len(fmt):
        token = _FORMAT_TOKEN.match(fmt, pos)
        if token is None:
            raise _Refuse()  # any other letter or symbol: not a form this module reads
        piece = token.group(0)
        pos = token.end()
        if piece in ("yyyy", "MM", "M", "dd", "d"):
            field = "year" if piece == "yyyy" else "month" if piece in ("MM", "M") else "day"
            if field in seen:
                raise _Refuse()
            seen.add(field)
            body = {"yyyy": r"\d{4}", "MM": r"\d{2}", "M": r"\d{1,2}", "dd": r"\d{2}", "d": r"\d{1,2}"}[piece]
            parts.append(f"(?P<{field}>{body})")
        else:
            separator = culture.date_sep if piece == "/" else piece
            parts.append(re.escape(separator))
    if seen != {"year", "month", "day"}:
        raise _Refuse()
    match = re.fullmatch("".join(parts), text)
    if match is None:
        raise _Invalid()
    return _make_day(int(match.group("year")), int(match.group("month")), int(match.group("day")))


def _parse_failure(kind: str) -> MError:
    if kind == "Duration":
        message = "We couldn't parse the Duration literal."
        return MError("Expression.Error", message, fmt=message)
    message = f"We couldn't parse the input provided as a {kind} value."
    reason = "Expression.Error" if kind == "Time" else "DataFormat.Error"
    return MError(reason, message, fmt=message)


def _culture_only(culture: MValue) -> MValue:
    """A From function's culture argument, as the options record the FromText functions read."""
    return V.Null() if isinstance(culture, V.Null) else V.Record((("Culture", culture),))


def _text_arg(value: MValue) -> Optional[str]:
    """The text of a parse argument: None for null or an empty text (a null answer)."""
    if isinstance(value, V.Null):
        return None
    if not isinstance(value, V.Text):
        raise _unsupported("text argument that is not text")
    return value.value or None


def _parse_as(text: str, kind: str, culture: _Culture, fmt: Optional[str] = None):
    """The value a parsed text gives for ``kind``; _Invalid -> the parse error; _Refuse -> an explicit ERR."""
    if fmt is not None:
        if kind != "Date":
            raise _Refuse()
        return V.Date(_date_from_format(text, fmt, culture))
    parsed = _parse(text, culture)
    if kind == "Date":
        if parsed.day is None or parsed.tod is not None or parsed.offset is not None:
            raise _Invalid()
        return V.Date(parsed.day)
    if kind == "DateTime":
        if parsed.day is None:
            raise _Refuse()  # a time alone takes today's date (the clock)
        if parsed.offset is not None:
            raise _Invalid()  # an offset is read only by DateTimeZone
        return V.DateTime(V.date_ticks(parsed.day) + (parsed.tod or 0))
    if kind == "DateTimeZone":
        if parsed.day is None or parsed.offset is None:
            raise _Refuse()  # no offset: the machine's time zone
        local = V.date_ticks(parsed.day) + (parsed.tod or 0)
        return V.make_datetimezone(local, parsed.offset)
    # Time: a time of day and nothing else
    if parsed.day is not None or parsed.offset is not None:
        raise _Invalid()
    return V.Time(parsed.tod)


def _parse_text_value(value: MValue, kind: str, options: MValue = V.Null()) -> MValue:
    text = _text_arg(value)
    if text is None:
        return V.Null()
    fmt, culture_value = _record_format(options)
    culture = _culture(culture_value)
    try:
        return _parse_as(text, kind, culture, fmt)
    except _Invalid:
        raise _parse_failure(kind)
    except _Refuse:
        raise _unsupported(f"{kind} text '{text}'") from None


def _record_format(options: MValue) -> tuple:
    if isinstance(options, V.Null):
        return None, V.Null()
    if not isinstance(options, V.Record):
        raise _unsupported("parse options that are not a record")
    for name in options.names():
        if name not in ("Format", "Culture"):
            raise _unsupported("parse option")
    fmt = options.get("Format")
    culture = options.get("Culture")
    return _text_option(fmt if fmt is not None else V.Null()), culture if culture is not None else V.Null()


def _date_from_text(value: MValue, options: MValue = V.Null()) -> MValue:
    return _parse_text_value(value, "Date", options)


def _duration_from_text(value: MValue, options: MValue = V.Null()) -> MValue:
    text = _text_arg(value)
    if text is None:
        return V.Null()
    match = _DURATION_CLOCK.fullmatch(text)
    if match:
        days = int(match.group(2) or 0)
        hours, minutes = int(match.group(3)), int(match.group(4))
        seconds = int(match.group(5) or 0)
        if hours > 23 or minutes > 59 or seconds > 59:
            raise _unsupported("duration outside the clock ranges")
        fraction = int((match.group(6) or "").ljust(7, "0") or 0)
        ticks = days * TPD + hours * TPH + minutes * TPM + seconds * TPS + fraction
        return V.make_duration(-ticks if match.group(1) else ticks)
    match = _DURATION_ISO.fullmatch(text)
    if match:
        if not any(match.groups()) or text.endswith("T"):
            raise _unsupported("ISO 8601 duration with no value")
        days, hours, minutes = (int(match.group(i) or 0) for i in (1, 2, 3))
        seconds = int(match.group(4) or 0)
        fraction = int((match.group(5) or "").ljust(7, "0") or 0)
        return V.make_duration(days * TPD + hours * TPH + minutes * TPM + seconds * TPS + fraction)
    if re.fullmatch(r"-?[\d.:]+", text) or text.startswith("P"):
        raise _unsupported("duration text")
    raise _parse_failure("Duration")


def _date_time_from_text(value: MValue, options: MValue = V.Null()) -> MValue:
    return _parse_text_value(value, "DateTime", options)


def _datetimezone_from_text(value: MValue, options: MValue = V.Null()) -> MValue:
    return _parse_text_value(value, "DateTimeZone", options)


def _time_from_text(value: MValue, options: MValue = V.Null()) -> MValue:
    return _parse_text_value(value, "Time", options)


# ---- numbers as dates and times (OLE automation dates) ----------------------

_OA_MIN, _OA_MAX = -657435.0, 2958466.0
_OA_DAY0 = _dt.date(1899, 12, 30).toordinal()  # the ordinal of OLE automation day 0


def _oa_number(value: MValue) -> float:
    x = value.value
    if not math.isfinite(x):
        raise _unsupported("non-finite number as a date")
    return x


def _oa_milliseconds(x: float) -> int:
    """x days (OLE automation) in whole milliseconds; a fraction that is not whole milliseconds is refused."""
    scaled = x * 86400000.0
    rounded = round(scaled)
    if abs(scaled - rounded) > 1e-6:
        raise _unsupported("fraction of a day finer than a millisecond")
    return rounded


def _date_from_number(x: float) -> MValue:
    if not _OA_MIN <= x < _OA_MAX:
        raise MError("DataFormat.Error", "We couldn't convert to Date.")
    return V.Date(_dt.date.fromordinal(_OA_DAY0 + math.floor(x)))


def _datetime_from_number(x: float) -> MValue:
    if not _OA_MIN <= x < _OA_MAX:
        raise _unsupported("number outside the OLE automation date range")
    return V.make_datetime((_OA_DAY0 - 1) * TPD + _oa_milliseconds(x) * 10000)


def _time_from_number(x: float) -> MValue:
    if not 0 <= x < 1:
        raise _unsupported("number outside one day as a time")
    milliseconds = _oa_milliseconds(x)
    if milliseconds >= 86400000:
        raise _unsupported("time at the end of the day")
    return V.Time(milliseconds * 10000)


# ---- the From functions -----------------------------------------------------

def _date_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Date):
        return value
    if isinstance(value, (V.DateTime, V.DateTimeZone)):
        return V.Date(V.ticks_to_date(value.ticks))
    if isinstance(value, V.Number):
        return _date_from_number(_oa_number(value))
    if isinstance(value, V.Text):
        return _date_from_text(value, _culture_only(culture))
    raise _unsupported(f"{V.type_display(value)} value as a Date")


def _date_time_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.DateTime):
        return value
    if isinstance(value, V.Date):
        return V.DateTime(V.date_ticks(value.value))
    if isinstance(value, V.Number):
        return _datetime_from_number(_oa_number(value))
    if isinstance(value, V.Text):
        return _date_time_from_text(value, _culture_only(culture))
    raise _unsupported(f"{V.type_display(value)} value as a DateTime")


def _datetimezone_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.DateTimeZone):
        return value
    if isinstance(value, V.Text):
        return _datetimezone_from_text(value, _culture_only(culture))
    raise _unsupported(f"{V.type_display(value)} value as a DateTimeZone (the machine's zone)")


def _time_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Time):
        return value
    if isinstance(value, V.Number):
        return _time_from_number(_oa_number(value))
    if isinstance(value, V.Text):
        return _time_from_text(value, _culture_only(culture))
    raise _unsupported(f"{V.type_display(value)} value as a Time")


def _duration_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Duration):
        return value
    if isinstance(value, V.Number):
        if not math.isfinite(value.value):
            raise _unsupported("non-finite number as a duration")
        return V.Duration(int(round(value.value * TPD)))
    if isinstance(value, V.Text):
        return _duration_from_text(value)
    raise _unsupported(f"{V.type_display(value)} value as a Duration")


# ---- DateTime and Time ------------------------------------------------------

def _hour(value: MValue) -> MValue:
    w = _when(value, TIME_ARG)
    return V.Null() if w is None else _num((w.wall % TPD) // TPH)


def _minute(value: MValue) -> MValue:
    w = _when(value, TIME_ARG)
    return V.Null() if w is None else _num((w.wall % TPH) // TPM)


def _second(value: MValue) -> MValue:
    w = _when(value, TIME_ARG)
    return V.Null() if w is None else V.Number((w.wall % TPM) / TPS)


def _start_of_hour(value: MValue) -> MValue:
    w = _when(value, TIME_ARG)
    return V.Null() if w is None else _result(w.kind, w.wall - w.wall % TPH, w.offset)


def _end_of_hour(value: MValue) -> MValue:
    w = _when(value, TIME_ARG)
    return V.Null() if w is None else _result(w.kind, w.wall - w.wall % TPH + TPH - 1, w.offset)


def _time_to_record(value: MValue) -> MValue:
    w = _when(value, ("time",))
    if w is None:
        return V.Null()
    return V.Record((("Hour", _num((w.wall % TPD) // TPH)), ("Minute", _num((w.wall % TPH) // TPM)),
                     ("Second", V.Number((w.wall % TPM) / TPS))))


def _time_to_text(value: MValue, options: MValue = V.Null()) -> MValue:
    w = _when(value, ("time",))
    if w is None:
        return V.Null()
    fmt, culture = _format_options(options)
    return V.Text(_format(w, fmt, _culture(culture)))


def _datetime_parts(w: _When) -> tuple:
    day = _day(w)
    tod = w.wall % TPD
    return (day.year, day.month, day.day, tod // TPH, (tod % TPH) // TPM, V.Number((tod % TPM) / TPS))


def _datetime_to_record(value: MValue) -> MValue:
    w = _when(value, ("datetime",), convert_from=("datetimezone",), convert_to="datetime")
    if w is None:
        return V.Null()
    y, mo, d, h, mi, s = _datetime_parts(w)
    return V.Record((("Year", _num(y)), ("Month", _num(mo)), ("Day", _num(d)), ("Hour", _num(h)),
                     ("Minute", _num(mi)), ("Second", s)))


def _datetime_to_text(value: MValue, options: MValue = V.Null()) -> MValue:
    w = _when(value, ("datetime",), convert_from=("datetimezone",), convert_to="datetime")
    if w is None:
        return V.Null()
    fmt, culture = _format_options(options)
    return V.Text(_format(w, fmt, _culture(culture)))


def _datetime_date(value: MValue) -> MValue:
    w = _when(value, ("datetime", "datetimezone"))
    return V.Null() if w is None else V.Date(_day(w))


def _datetime_time(value: MValue) -> MValue:
    w = _when(value, ("datetime", "datetimezone"))
    return V.Null() if w is None else V.Time(w.wall % TPD)


def _add_zone(value: MValue, hours: MValue, minutes: MValue = V.Null()) -> MValue:
    w = _when(value, ("datetime",), convert_from=("datetimezone",), convert_to="datetime")
    if w is None:
        return V.Null()
    total = _whole(hours, "hours") * 60 + (0 if isinstance(minutes, V.Null) else _whole(minutes, "minutes"))
    return V.make_datetimezone(w.wall, total)


# ---- DateTimeZone -------------------------------------------------------------

def _dtz(value: MValue) -> Optional[_When]:
    return _when(value, ("datetimezone",))


def _zone_hours(value: MValue) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    sign = -1 if w.offset < 0 else 1
    return _num(sign * (abs(w.offset) // 60))


def _zone_minutes(value: MValue) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    sign = -1 if w.offset < 0 else 1
    return _num(sign * (abs(w.offset) % 60))


def _to_utc(value: MValue) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    return V.make_datetimezone(w.wall - w.offset * TPM, 0)


def _switch_zone(value: MValue, hours: MValue, minutes: MValue = V.Null()) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    new_offset = _whole(hours, "hours") * 60 + (0 if isinstance(minutes, V.Null) else _whole(minutes, "minutes"))
    utc = w.wall - w.offset * TPM
    return V.make_datetimezone(utc + new_offset * TPM, new_offset)


def _remove_zone(value: MValue) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    return V.make_datetime(w.wall)


def _datetimezone_to_record(value: MValue) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    y, mo, d, h, mi, s = _datetime_parts(w)
    return V.Record((("Year", _num(y)), ("Month", _num(mo)), ("Day", _num(d)), ("Hour", _num(h)),
                     ("Minute", _num(mi)), ("Second", s), ("ZoneHours", _zone_hours(value)),
                     ("ZoneMinutes", _zone_minutes(value))))


def _datetimezone_to_text(value: MValue, options: MValue = V.Null()) -> MValue:
    w = _dtz(value)
    if w is None:
        return V.Null()
    fmt, culture = _format_options(options)
    return V.Text(_format(w, fmt, _culture(culture)))


def _to_local(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    raise _unsupported("conversion to the machine's local time zone")


# ---- Duration -----------------------------------------------------------------

def _dur(value: MValue) -> Optional[int]:
    if isinstance(value, V.Null):
        return None
    if not isinstance(value, V.Duration):
        raise _unsupported(f"{V.type_display(value)} value as a Duration")
    return value.ticks


def _signed(sign: int, magnitude) -> V.Number:
    return V.Number(float(sign * magnitude) + 0.0)


def _duration_days(value: MValue) -> MValue:
    t = _dur(value)
    if t is None:
        return V.Null()
    return _signed(-1 if t < 0 else 1, abs(t) // TPD)


def _duration_hours(value: MValue) -> MValue:
    t = _dur(value)
    if t is None:
        return V.Null()
    return _signed(-1 if t < 0 else 1, (abs(t) % TPD) // TPH)


def _duration_minutes(value: MValue) -> MValue:
    t = _dur(value)
    if t is None:
        return V.Null()
    return _signed(-1 if t < 0 else 1, (abs(t) % TPH) // TPM)


def _duration_seconds(value: MValue) -> MValue:
    t = _dur(value)
    if t is None:
        return V.Null()
    return _signed(-1 if t < 0 else 1, (abs(t) % TPM) / TPS)


def _total(divisor: int):
    def invoke(value: MValue) -> MValue:
        t = _dur(value)
        return V.Null() if t is None else V.Number(t * (1.0 / divisor))  # .NET: ticks * (1 / ticks per unit)

    return invoke


def _duration_to_record(value: MValue) -> MValue:
    if _dur(value) is None:
        return V.Null()
    return V.Record((("Days", _duration_days(value)), ("Hours", _duration_hours(value)),
                     ("Minutes", _duration_minutes(value)), ("Seconds", _duration_seconds(value))))


def _duration_to_text(value: MValue) -> MValue:
    from .canonical import duration_text

    t = _dur(value)
    return V.Null() if t is None else V.Text(duration_text(t))


# ---- registration -------------------------------------------------------------

DATE_GLOBALS: dict = {
    "Date.Year": _native((("date", False),), _date_component(_year)),
    "Date.Month": _native((("date", False),), _date_component(_month)),
    "Date.Day": _native((("date", False),), _date_component(_day_of_month)),
    "Date.DayOfYear": _native((("date", False),), _date_component(_day_of_year)),
    "Date.DaysInMonth": _native((("date", False),), _date_component(_days_in_month)),
    "Date.QuarterOfYear": _native((("date", False),), _date_component(_quarter)),
    "Date.IsLeapYear": _native((("date", False),), _is_leap),
    "Date.DayOfWeek": _native((("date", False), ("firstDayOfWeek", True)), _day_of_week),
    "Date.WeekOfMonth": _native((("date", False), ("firstDayOfWeek", True)), _week_of_month),
    "Date.WeekOfYear": _native((("date", False), ("firstDayOfWeek", True)), _week_of_year),
    "Date.StartOfWeek": _native((("date", False), ("firstDayOfWeek", True)), _start_of_week),
    "Date.EndOfWeek": _native((("date", False), ("firstDayOfWeek", True)), _end_of_week),
    "Date.StartOfDay": _native((("date", False),), _start_of_day),
    "Date.EndOfDay": _native((("date", False),), _end_of_day),
    "Date.StartOfMonth": _native((("date", False),), _start_of_month),
    "Date.EndOfMonth": _native((("date", False),), _end_of_month),
    "Date.StartOfQuarter": _native((("date", False),), _start_of_quarter),
    "Date.EndOfQuarter": _native((("date", False),), _end_of_quarter),
    "Date.StartOfYear": _native((("date", False),), _start_of_year),
    "Date.EndOfYear": _native((("date", False),), _end_of_year),
    "Date.AddDays": _native((("date", False), ("numberOfDays", False)), _add_days),
    "Date.AddWeeks": _native((("date", False), ("numberOfWeeks", False)),
                             lambda v, n: _add_days(v, V.Number(_whole(n, "week count") * 7.0))),
    "Date.AddMonths": _native((("date", False), ("numberOfMonths", False)),
                              lambda v, n: _add_month_count(v, n, 1)),
    "Date.AddQuarters": _native((("date", False), ("numberOfQuarters", False)),
                                lambda v, n: _add_month_count(v, n, 3)),
    "Date.AddYears": _native((("date", False), ("numberOfYears", False)),
                             lambda v, n: _add_month_count(v, n, 12)),
    "Date.MonthName": _native((("date", False), ("culture", True)), _month_name),
    "Date.DayOfWeekName": _native((("date", False), ("culture", True)), _day_of_week_name),
    "Date.ToRecord": _native((("date", False),), _date_to_record),
    "Date.ToText": _native((("date", False), ("format", True)), _date_to_text),
    "Date.FromText": _native((("text", False), ("options", True)), _date_from_text),
    "Date.From": _native((("value", False), ("culture", True)), _date_from),
    "Date.Type": V.TypeValue("date"),
    "Day.Sunday": V.Number(0.0),
    "Day.Monday": V.Number(1.0),
    "Day.Tuesday": V.Number(2.0),
    "Day.Wednesday": V.Number(3.0),
    "Day.Thursday": V.Number(4.0),
    "Day.Friday": V.Number(5.0),
    "Day.Saturday": V.Number(6.0),
}

DATETIME_GLOBALS: dict = {
    "DateTime.Date": _native((("datetime", False),), _datetime_date),
    "DateTime.Time": _native((("datetime", False),), _datetime_time),
    "DateTime.ToRecord": _native((("datetime", False),), _datetime_to_record),
    "DateTime.ToText": _native((("datetime", False), ("format", True)), _datetime_to_text),
    "DateTime.FromText": _native((("text", False), ("options", True)), _date_time_from_text),
    "DateTime.From": _native((("value", False), ("culture", True)), _date_time_from),
    "DateTime.AddZone": _native((("datetime", False), ("hours", False), ("minutes", True)), _add_zone),
    "DateTime.Type": V.TypeValue("datetime"),
}

DATETIMEZONE_GLOBALS: dict = {
    "DateTimeZone.ZoneHours": _native((("datetimezone", False),), _zone_hours),
    "DateTimeZone.ZoneMinutes": _native((("datetimezone", False),), _zone_minutes),
    "DateTimeZone.ToUtc": _native((("datetimezone", False),), _to_utc),
    "DateTimeZone.SwitchZone": _native((("datetimezone", False), ("hours", False), ("minutes", True)),
                                       _switch_zone),
    "DateTimeZone.RemoveZone": _native((("datetimezone", False),), _remove_zone),
    "DateTimeZone.ToRecord": _native((("datetimezone", False),), _datetimezone_to_record),
    "DateTimeZone.ToText": _native((("datetimezone", False), ("format", True)), _datetimezone_to_text),
    "DateTimeZone.FromText": _native((("text", False), ("options", True)), _datetimezone_from_text),
    "DateTimeZone.From": _native((("value", False), ("culture", True)), _datetimezone_from),
    "DateTimeZone.ToLocal": _native((("datetimezone", False),), _to_local),
    "DateTimeZone.Type": V.TypeValue("datetimezone"),
}

TIME_GLOBALS: dict = {
    "Time.Hour": _native((("time", False),), _hour),
    "Time.Minute": _native((("time", False),), _minute),
    "Time.Second": _native((("time", False),), _second),
    "Time.StartOfHour": _native((("time", False),), _start_of_hour),
    "Time.EndOfHour": _native((("time", False),), _end_of_hour),
    "Time.ToRecord": _native((("time", False),), _time_to_record),
    "Time.ToText": _native((("time", False), ("format", True)), _time_to_text),
    "Time.FromText": _native((("text", False), ("options", True)), _time_from_text),
    "Time.From": _native((("value", False), ("culture", True)), _time_from),
    "Time.Type": V.TypeValue("time"),
}

DURATION_GLOBALS: dict = {
    "Duration.Days": _native((("duration", False),), _duration_days),
    "Duration.Hours": _native((("duration", False),), _duration_hours),
    "Duration.Minutes": _native((("duration", False),), _duration_minutes),
    "Duration.Seconds": _native((("duration", False),), _duration_seconds),
    "Duration.TotalDays": _native((("duration", False),), _total(TPD)),
    "Duration.TotalHours": _native((("duration", False),), _total(TPH)),
    "Duration.TotalMinutes": _native((("duration", False),), _total(TPM)),
    "Duration.TotalSeconds": _native((("duration", False),), _total(TPS)),
    "Duration.ToRecord": _native((("duration", False),), _duration_to_record),
    "Duration.ToText": _native((("duration", False),), _duration_to_text),
    "Duration.FromText": _native((("text", False), ("options", True)), _duration_from_text),
    "Duration.From": _native((("value", False), ("culture", True)), _duration_from),
    "Duration.Type": V.TypeValue("duration"),
}

def _clock_refusal(name: str):
    """A function whose answer depends on the clock or the machine's zone: an explicit ERR, whatever the argument."""
    def invoke(*_args: MValue) -> MValue:
        raise _unsupported(f"{name} (depends on the clock or the machine's time zone)")

    return V.Function((V.ParamSpec("value", None, True),), lambda bound: invoke(*bound))


_CLOCK_NAMES = (
    *(f"Date.{prefix}{span}" for prefix in ("IsInCurrent", "IsInNext", "IsInPrevious")
      for span in ("Day", "Week", "Month", "Quarter", "Year")),
    "Date.IsInYearToDate",
    *(f"DateTime.{prefix}{span}" for prefix in ("IsInCurrent", "IsInNext", "IsInPrevious")
      for span in ("Day", "Week", "Month", "Quarter", "Year", "Hour", "Minute", "Second")),
    "DateTime.IsInYearToDate", "DateTime.LocalNow", "DateTime.FixedLocalNow", "DateTime.FromFileTime",
    *(f"DateTimeZone.{prefix}{span}" for prefix in ("IsInCurrent", "IsInNext", "IsInPrevious")
      for span in ("Day", "Week", "Month", "Quarter", "Year", "Hour", "Minute", "Second")),
    "DateTimeZone.IsInYearToDate", "DateTimeZone.LocalNow", "DateTimeZone.UtcNow",
    "DateTimeZone.FixedLocalNow", "DateTimeZone.FixedUtcNow",
    "Time.IsInCurrentHour", "Time.IsInNextHour", "Time.IsInPreviousHour",
)

CLOCK_GLOBALS: dict = {name: _clock_refusal(name) for name in _CLOCK_NAMES}

DATE_TIME_GLOBALS: dict = {**DATE_GLOBALS, **DATETIME_GLOBALS, **DATETIMEZONE_GLOBALS, **TIME_GLOBALS,
                           **DURATION_GLOBALS, **CLOCK_GLOBALS}
