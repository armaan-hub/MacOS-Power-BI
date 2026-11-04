"""DAX date/time values and functions, matching Power BI Desktop 2.157.879.0 (en-US).

A DateTime is a number of days since 1899-12-30 with a "date" tag (``DaxDateTime``), so arithmetic, comparisons and
``INT``/``VALUE`` work on the number while ``&``, ``FORMAT`` and the display use date text.  Compared live through
``tools/dax_battery_typed.json`` and the date columns of the standing test workbook.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP
import re

from analytics_studio import dax_typed

EPOCH = datetime(1899, 12, 30)
NEAREST_SECOND = "nearest-second"
_SECONDS_PER_DAY = Decimal(86400)
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class DaxDateTime(Decimal):
    """A DAX DateTime: days since 1899-12-30 (the fraction is the time of day)."""

    __slots__ = ()


def from_datetime(moment: datetime | date) -> DaxDateTime:
    if not isinstance(moment, datetime):
        moment = datetime(moment.year, moment.month, moment.day)
    delta = moment - EPOCH
    seconds = Decimal(delta.seconds) + Decimal(delta.microseconds) / Decimal(1_000_000)
    return DaxDateTime(Decimal(delta.days) + seconds / _SECONDS_PER_DAY)


def to_datetime(serial: Decimal, rounding: str = ROUND_HALF_UP, shown: bool = False) -> datetime:
    if not serial.is_finite():
        raise dax_typed._error("An argument has the wrong data type or the result is too large or too small.")
    if serial < 0 and serial != serial.to_integral_value() and not shown:
        # live Power BI counts the time of day of a serial before day zero forward from the day it follows (OLE) and rounds it in a
        # way that is not modelled for the date functions (iteration 84, 800 probes): refused rather than guessed. Only the display of
        # such a value (shown=True, Task 40 Part C) is measured.
        raise dax_typed._error("A time of day before December 30, 1899 is not supported in the local engine.")
    if serial < 0:
        days = serial.to_integral_value(rounding=ROUND_CEILING)
        scaled = (abs(serial) - abs(days)) * _SECONDS_PER_DAY
    else:
        days = serial.to_integral_value(rounding=ROUND_FLOOR)
        scaled = (serial - days) * _SECONDS_PER_DAY
    if rounding == ROUND_DOWN:
        seconds = scaled.quantize(Decimal(1), rounding=ROUND_DOWN)
    elif rounding == NEAREST_SECOND:  # live Power BI: WEEKDAY / WEEKNUM take the day of the time of day rounded to the nearest second
        if 0 < serial < 1 and abs(scaled - scaled.quantize(Decimal(1), rounding=ROUND_FLOOR) - Decimal("0.5")) < Decimal("0.000000001"):
            # a time of day that is an exact half second (FORMAT(1.5/86400,"hh:nn:ss") is 00:00:02 in Power BI): the Decimal here has
            # lost the last digits of 1.5/86400 and would round it down, the double there is a tie that rounds up
            scaled = scaled.quantize(Decimal(1), rounding=ROUND_FLOOR) + Decimal("0.5")
        seconds = scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    else:
        if serial >= 1_000_000 and abs(scaled - scaled.quantize(Decimal(1), rounding=ROUND_HALF_UP)) > Decimal("0.0001"):
            # live Power BI: far from day zero (years after 4700) the fraction of a second is not reproduced by the local engine
            # (SECOND(DATE(9999,12,31)+0.0001) is 7 there), so only whole seconds are answered
            raise dax_typed._error("A date with a fraction of a second so far from 1899 is not supported in the local engine.")
        # live Power BI: the time of day is held in ticks of 1/300 s (rounded to the nearest tick) and shown without its fraction of a second
        ticks = (scaled * 300).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        seconds = ticks // 300
    try:
        moment = EPOCH + timedelta(days=int(days), seconds=int(seconds))
    except OverflowError as exc:
        raise dax_typed._error("A date is outside the supported range.") from exc
    if moment.year < 100:
        raise dax_typed._error("A date before January 1, 100 is not supported.")  # Power BI clamps such results to 01/01/0100
    return moment


def tick_round(serial: Decimal) -> Decimal:
    """A date value as Power BI holds it: the time of day rounded to the nearest tick of 1/300 s (INT(DATE(2024,2,29)+0.99999999) is
    45352, live iteration 84)."""
    if not serial.is_finite() or serial == serial.to_integral_value():
        return serial
    return (serial * 25_920_000).quantize(Decimal(1), rounding=ROUND_HALF_UP) / 25_920_000


def is_date(value: object) -> bool:
    return isinstance(value, DaxDateTime)


def _shown_moment(value: Decimal, rounding: str = ROUND_HALF_UP) -> datetime:
    """Task 21 Part D: a date beside Infinity or NaN shows as Power BI prints it: NaN as day zero, +Infinity as the last
    second of 9999 and -Infinity as 01/01/0100 (the same printing as CONVERT of a non-finite number to DATETIME)."""
    if not value.is_finite():
        if value.is_nan():
            return EPOCH
        return datetime(9999, 12, 31, 23, 59, 59) if value > 0 else datetime(100, 1, 1)
    return to_datetime(value, rounding, shown=True)


def _half_second_before_zero(value: Decimal) -> bool:
    """A serial below zero (this includes the days between -1 and 0) whose time of day is an exact half second. Power BI rounds such a
    time up or down by the last digit of its double, differently from one date to the next (DATE(1800,1,1)+1.5/86400 shows 11:59:58 PM,
    DATE(1850,7,4)+1.5/86400 shows 11:59:59 PM, Task 40 t40h, 1,458 probes, 16 wrong): it has no rule that is reproduced here, so the
    text and FORMAT of such a value are refused."""
    if not value.is_finite() or value >= 0 or value == value.to_integral_value():
        return False
    scaled = (abs(value) - abs(value.to_integral_value(rounding=ROUND_CEILING))) * _SECONDS_PER_DAY
    return abs(scaled - scaled.quantize(Decimal(1), rounding=ROUND_FLOOR) - Decimal("0.5")) < Decimal("0.001")


def _refuse_half_second(value: Decimal) -> None:
    if _half_second_before_zero(value):
        raise dax_typed._error("A time of day before December 30, 1899 on an exact half second is not supported in the local engine.")


def date_text(value: Decimal, pad_year: bool = False) -> str:
    """The text of a date in a concatenation: M/d/yyyy, plus h:mm:ss AM/PM when there is a time of day (FORMAT "General Date" pads the
    year to four digits, a concatenation does not: live Power BI, 1/1/0100 and 1/1/100)."""
    if value.is_infinite():
        raise dax_typed._error("The parameter is incorrect.")  # Task 21 Part D: a date beside +Infinity or -Infinity has no text (NaN is day zero, as the text of a time)
    _refuse_half_second(value)
    moment = _shown_moment(value, NEAREST_SECOND)  # live Power BI: the text of a date shows the time of day rounded to the nearest second
    time_text = f"{moment.hour % 12 or 12}:{moment.minute:02d}:{moment.second:02d} {'AM' if moment.hour < 12 else 'PM'}"
    if (moment.year, moment.month, moment.day) == (1899, 12, 30):
        return time_text  # day zero is a time of day only
    text = f"{moment.month}/{moment.day}/{moment.year:04d}" if pad_year else f"{moment.month}/{moment.day}/{moment.year}"
    if moment.hour or moment.minute or moment.second:
        text += " " + time_text
    return text


def oracle_text(value: Decimal) -> str:
    """The text Power BI's ADOMD client shows for a DateTime result (used by the comparison harness)."""
    return _shown_moment(value).strftime("%m/%d/%Y %H:%M:%S")


# ---------------------------------------------------------------------------------------------- parsing

_TEXT_DATE_FORMATS = (
    "%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%d-%b-%Y",
    "%d-%b-%y", "%d-%B-%Y", "%d/%m/%Y",
)


def parse_date_text(text: str) -> DaxDateTime:
    cleaned = " ".join(text.split())
    for pattern in _TEXT_DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, pattern)
        except ValueError:
            continue
        # live Power BI (iteration 84, critic): a year below 100 is a two-digit year, 00-49 are 20xx and 50-99 are 19xx
        # ("1/1/50" is 1950, "1/1/0001" is 2001); strptime reads %y with the pivot at 69
        two_digit = parsed.year % 100 if "%y" in pattern else parsed.year if parsed.year < 100 else None
        if two_digit is not None:
            try:
                parsed = parsed.replace(year=(2000 if two_digit < 50 else 1900) + two_digit)
            except ValueError as error:
                raise dax_typed._error(f"Cannot convert value '{text}' of type Text to type Date.") from error
        return from_datetime(parsed)
    raise dax_typed._error(f"Cannot convert value '{text}' of type Text to type Date.")


def _settled_before_zero(value: object) -> bool:
    """A serial before day zero with a time of day at least a second from either end of the day: the components of such a value
    (YEAR, MONTH, DAY, HOUR, MINUTE, SECOND, WEEKDAY, FORMAT) were measured in live Power BI (Task 40, 1,700 probes). A time within a
    second of midnight (DAY(DATE(1800,1,1)+0.000001) is 1 there, 2 by the conversion) and every other date function (DATEDIFF, WEEKNUM,
    iteration 84) are not settled and stay refused."""
    if not isinstance(value, Decimal) or not value.is_finite() or value >= 0 or value == value.to_integral_value():
        return False
    fraction = abs(value) - abs(value.to_integral_value(rounding=ROUND_CEILING))
    return Decimal(1) / _SECONDS_PER_DAY <= fraction <= 1 - Decimal(1) / _SECONDS_PER_DAY


def _moment(value: object, rounding: str = ROUND_HALF_UP, shown: bool = False) -> datetime | None:
    """A date argument: a DateTime or number, or text that reads as a date; blank gives None."""
    if value is None:
        return None
    if isinstance(value, str):
        return to_datetime(parse_date_text(value), rounding)
    if isinstance(value, bool):
        return to_datetime(Decimal(int(value)), rounding)
    return to_datetime(value, rounding, shown=shown)  # type: ignore[arg-type]


_MONTH_DAY_TEXT = re.compile(r"(\d{1,2})[/-](\d{1,2})")  # live Power BI: "1/2" and "1-2" are month and day of the current year


def text_serial(text: str) -> Decimal | None:
    """A text read as a date, a time or both, by the parsers behind DATEVALUE and TIMEVALUE, as its serial number (days since
    1899-12-30, the time of day as a fraction); None when it reads as neither (Task 19 Part E)."""
    from .measures import MeasureRuntimeError  # late import: measures imports this module

    for reader in (parse_date_text, _time_value):
        try:
            return Decimal(reader(text))
        except MeasureRuntimeError:
            continue
    found = _MONTH_DAY_TEXT.fullmatch(text.strip())
    if found is None:
        return None
    try:
        return Decimal(from_datetime(datetime(date.today().year, int(found.group(1)), int(found.group(2)))))
    except ValueError:
        return None


_DATE_SHAPED_TEXT = re.compile(r"\d[\d ./,:-]*\d")
_ISO_DATE_SHAPE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")  # read strictly: a month or day out of range ("2020-13-01") is an error, not another reading


def date_shaped_text(text: str) -> bool:
    """A text of digits and date separators that begins and ends with a digit and is not a whole number ("1 1/2"): Power BI may read it as a
    date that no reader here models. Every other text that is neither a number nor a date is an ordinary conversion error."""
    shown = text.strip()
    return _DATE_SHAPED_TEXT.fullmatch(shown) is not None and not shown.isdigit() and _ISO_DATE_SHAPE.fullmatch(shown) is None


def datetime_text(text: str) -> DaxDateTime:
    """CONVERT(text, DATETIME) is strict (Task 19 Part E): a text that reads as a date or a time is that moment. A whole number is the
    error "Cannot convert value 'x' of type Text to type Date." and so is any text that is not date-shaped; a date-shaped one it cannot read is refused."""
    serial = text_serial(text)
    if serial is not None:
        return DaxDateTime(serial)
    shown = text.strip()
    if date_shaped_text(shown):  # "1 1/2", "1,000": a shape no reader here models
        raise dax_typed.refusal(f"The local engine does not model the text '{shown}' as a date.")
    raise dax_typed._error(f"Cannot convert value '{shown}' of type Text to type Date.")


# ------------------------------------------------------------------------------------------- functions


def _make_date(year: object, month: object, day: object) -> DaxDateTime:
    y = dax_typed.whole(year, "DATE")
    m = dax_typed.whole(month, "DATE")
    d = dax_typed.whole(day, "DATE")
    failure = "An argument of function 'DATE' has the wrong data type or the result is too large or too small."
    if 0 <= y < 50:
        y += 2000  # two-digit years (live Power BI 2.157): 0-49 are 20xx, 50-99 are 19xx
    elif 50 <= y < 100:
        y += 1900
    elif -1800 <= y < 0:
        y += 1900  # a negative year counts back from 1900 (DATE(-5,1,1) is 1895)
    total = y * 12 + (m - 1)
    y, m = divmod(total, 12)
    m += 1
    if y < 1 or y > 9999 or d == 0 or (y, m, d) == (1900, 2, 29):  # live Power BI: the fake leap day of 1900 is an error
        raise dax_typed._error(failure)
    try:
        return from_datetime(datetime(y, m, 1) + timedelta(days=d - 1))
    except OverflowError as exc:
        raise dax_typed._error(failure) from exc


_TIME_TEXT = re.compile(r"(?i)(?:(?P<date>\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4})\s+)?(?P<h>\d{1,2})[:.](?P<m>\d{1,2})(?::(?P<s>\d{1,2}))?(?:\s*(?P<ap>[ap])m?)?")


def _time_value(text: str) -> DaxDateTime:
    """TIMEVALUE as Power BI reads it (iteration 84, live): h:m[:s] or h.m with an optional A / P / AM / PM and an optional date in front;
    an hour above 23, a minute or second above 59, a sign, a fraction of a second or any other text is an error."""
    failure = dax_typed._error(f"Cannot convert value '{text}' of type Text to type Date.")
    found = _TIME_TEXT.fullmatch(text.strip())
    if found is None:
        raise failure
    hour, minute, second = int(found.group("h")), int(found.group("m")), int(found.group("s") or 0)
    if hour > 23 or minute > 59 or second > 59:
        raise failure
    if found.group("date"):
        try:
            parse_date_text(found.group("date"))
        except Exception as error:
            raise failure from error
    meridiem = found.group("ap")
    if meridiem:
        if meridiem.lower() == "a":
            hour = 0 if hour == 12 else hour
        elif hour < 12:
            hour += 12
    return DaxDateTime(Decimal(hour * 3600 + minute * 60 + second) / _SECONDS_PER_DAY)


_CLOCK_TEXT = re.compile(r"\s*([0-9]{1,2})(?::([0-9]{1,2})(?::([0-9]{1,2}))?)?\s*([AaPp][Mm])?\s*")


def _clock_text(text: str) -> tuple[int, int, int] | None:
    """Time-only text for HOUR / MINUTE / SECOND (iteration 88, live): H:MM or H:MM:SS with an optional AM / PM, or H AM / H PM;
    PM adds 12 below noon, 12 AM is hour 0, an hour above 12 with PM is kept as written. Anything else (hour 24, minute or second
    above 59, dots, fractions, other spellings) is not decided here and goes the old way."""
    found = _CLOCK_TEXT.fullmatch(text)
    if found is None:
        return None
    hour_text, minute_text, second_text, meridiem = found.groups()
    if minute_text is None and meridiem is None:
        return None
    hour, minute, second = int(hour_text), int(minute_text or 0), int(second_text or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    if meridiem:
        pm = meridiem[0] in "Pp"
        if hour == 0:
            if pm or minute_text is None:
                return None
        elif hour > 12:
            if not pm:
                return None
        elif pm and hour < 12:
            hour += 12
        elif not pm and hour == 12:
            hour = 0
    return hour, minute, second


def _weekday_index(moment: datetime, week_start: int) -> int:
    """0 for the first day of the week; week_start is 0 for Monday."""
    return (moment.weekday() - week_start) % 7


def _weekday(moment: datetime, kind: int) -> int:
    if kind == 1:
        return _weekday_index(moment, 6) + 1
    if kind == 2:
        return _weekday_index(moment, 0) + 1
    if kind == 3:
        return _weekday_index(moment, 0)
    if 11 <= kind <= 17:
        return _weekday_index(moment, (kind - 11)) + 1
    raise dax_typed._error("An argument of function 'WEEKDAY' has the wrong data type or the result is too large or too small.")


def _weeknum(moment: datetime, kind: int) -> int:
    if kind == 21:
        if moment.year < 1753:
            raise dax_typed._error("ISO week numbers before 1753 are not supported in the local engine.")  # live: WEEKNUM(DATE(100,1,1),21) is 52, not 53
        return moment.isocalendar()[1]
    week_start = {1: 6, 2: 0}.get(kind, kind - 11 if 11 <= kind <= 17 else None)
    if week_start is None:
        raise dax_typed._error("An argument of function 'WEEKNUM' has the wrong data type or the result is too large or too small.")
    first = datetime(moment.year, 1, 1)
    offset = _weekday_index(first, week_start)
    return (moment.timetuple().tm_yday - 1 + offset) // 7 + 1


def _add_months(moment: datetime, months: int) -> datetime:
    total = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if not 1 <= year <= 9999:
        raise dax_typed._error("A date is outside the supported range.")
    return moment.replace(year=year, month=month, day=min(moment.day, monthrange(year, month)[1]))


def _datediff(start: datetime, end: datetime, interval: str) -> Decimal:
    if interval == "YEAR":
        return Decimal(end.year - start.year)
    if interval == "QUARTER":
        return Decimal((end.year * 4 + (end.month - 1) // 3) - (start.year * 4 + (start.month - 1) // 3))
    if interval == "MONTH":
        return Decimal((end.year * 12 + end.month) - (start.year * 12 + start.month))
    stamp = {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}.get(interval)
    if interval == "WEEK":  # weeks start on Sunday; 1899-12-31 was a Sunday
        week = lambda m: (datetime(m.year, m.month, m.day) - datetime(1899, 12, 31)).days // 7
        return Decimal(week(end) - week(start))
    if stamp is None:
        raise dax_typed._error("DATEDIFF needs SECOND, MINUTE, HOUR, DAY, WEEK, MONTH, QUARTER or YEAR.")
    floor = lambda m: int((m - EPOCH).total_seconds() // stamp)
    return Decimal(floor(end) - floor(start))


def date_function(function: str, args: list[object], interval: str | None = None) -> object:
    """Evaluate a date function over already-evaluated arguments (None is BLANK)."""
    if function == "TODAY":
        return from_datetime(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    if function == "NOW":
        return from_datetime(datetime.now().replace(microsecond=0))
    if function == "UTCTODAY":
        return from_datetime(datetime.now(timezone.utc).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0))
    if function == "UTCNOW":
        return from_datetime(datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
    if function == "DATE":
        return _make_date(*args)
    if function == "TIME":
        if all(value is None for value in args):
            return None
        hours, minutes, seconds = (dax_typed.whole(value, "TIME") for value in args)
        total = hours * 3600 + minutes * 60 + seconds
        if total < 0 or any(not -32768 <= part <= 32767 for part in (hours, minutes, seconds)):
            # live Power BI (iteration 84, critic; 416 probes): an argument outside a signed 16-bit number, or a negative total, is an error
            raise dax_typed._error("An argument of function 'TIME' has the wrong data type or the result is too large or too small.")
        return DaxDateTime(Decimal(total % 86400) / _SECONDS_PER_DAY)
    if function == "DATEVALUE":
        if args[0] is None:
            return None
        return from_datetime(to_datetime(parse_date_text(dax_typed.to_text(args[0]))).replace(hour=0, minute=0, second=0))
    if function == "TIMEVALUE":
        if args[0] is None:
            return None
        return _time_value(dax_typed.to_text(args[0]))
    if function == "DATEDIFF":
        start, end = _moment(args[0], ROUND_DOWN), _moment(args[1], ROUND_DOWN)
        if start is None or end is None:
            return None
        return _datediff(start, end, str(interval))
    if function in {"HOUR", "MINUTE", "SECOND"} and isinstance(args[0], str):
        clock = _clock_text(args[0])
        if clock is not None:
            return Decimal(clock[("HOUR", "MINUTE", "SECOND").index(function)])
    if function in {"HOUR", "MINUTE", "SECOND"} and isinstance(args[0], Decimal) and args[0].is_finite() and args[0] < 0:
        # live Power BI (Task 40 review): SECOND(-3+0.999) is 27, where the same value shown as a date and time ends in :26 (the time of day, 1:26.4, is
        # rounded up there and down there). Only the one value 0.999 was measured, so a whole-second time answers as always, and a time with a fraction
        # of a second is refused for SECOND and, for HOUR and MINUTE, wherever rounding up would change the answer.
        fraction_ticks = ((abs(args[0]) - abs(args[0].to_integral_value(rounding=ROUND_CEILING))) * _SECONDS_PER_DAY * 300).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        if fraction_ticks % 300:
            unit = {"HOUR": 3600, "MINUTE": 60, "SECOND": 1}[function]
            whole_seconds = int(fraction_ticks) // 300
            if function == "SECOND" or (whole_seconds + 1) // unit != whole_seconds // unit:
                raise dax_typed._error(f"{function} of a time before December 30, 1899 with a fraction of a second is not supported in the local engine.")
    if function in {"YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "QUARTER"} and isinstance(args[0], Decimal) and not args[0].is_finite():
        moment = EPOCH
    elif function in {"EDATE", "EOMONTH"} and args[0] is not None and not isinstance(args[0], str):
        if not Decimal(args[0]).is_finite():
            raise dax_typed._error("An argument has the wrong data type or the result is too large or too small.")
        int_day = Decimal(args[0]).to_integral_value(rounding=ROUND_FLOOR)
        moment = EPOCH + timedelta(days=int(int_day))
    else:
        moment = _moment(args[0], ROUND_FLOOR if function in {"HOUR", "MINUTE", "SECOND"} else NEAREST_SECOND if function in {"WEEKDAY", "WEEKNUM"} else ROUND_HALF_UP,
                         shown=function in {"YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND", "WEEKDAY"} and _settled_before_zero(args[0]))
    if moment is None:
        if function in {"EDATE", "EOMONTH"} and args[1] is not None:
            dax_typed.whole(args[1], function)  # Task 20 F4: a BLANK date still reads the months; an Infinity, a NaN or a text there is the error
        return None
    if function == "YEAR":
        return Decimal(moment.year)
    if function == "MONTH":
        return Decimal(moment.month)
    if function == "DAY":
        return Decimal(moment.day)
    if function == "HOUR":
        return Decimal(moment.hour)
    if function == "MINUTE":
        return Decimal(moment.minute)
    if function == "SECOND":
        return Decimal(moment.second)
    if function == "QUARTER":
        return Decimal((moment.month - 1) // 3 + 1)
    if function == "WEEKDAY":
        return Decimal(_weekday(moment, dax_typed.whole(args[1], function) if len(args) > 1 else 1))
    if function == "WEEKNUM":
        return Decimal(_weeknum(moment, dax_typed.whole(args[1], function) if len(args) > 1 else 1))
    months = dax_typed.whole(args[1], function)
    if function == "EDATE":
        return from_datetime(_add_months(moment.replace(hour=0, minute=0, second=0), months))
    if function == "EOMONTH":
        shifted = _add_months(moment.replace(day=1, hour=0, minute=0, second=0), months)
        return from_datetime(shifted.replace(day=monthrange(shifted.year, shifted.month)[1]))
    raise dax_typed._error(f"Function {function} is not supported by the local DAX engine.")


# --------------------------------------------------------------------------------------------- formats

_NAMED_DATE_FORMATS = {
    "general date": "general", "short date": "M/d/yyyy", "ddddd": "M/d/yyyy", "long date": "dddd, MMMM d, yyyy",
    "dddddd": "dddd, MMMM d, yyyy", "ttttt": "h:mm:ss AM/PM", "medium date": "dd-MMM-yy", "long time": "h:mm:ss tt", "medium time": "hh:mm tt",
    "short time": "HH:mm",
}


def format_date(value: Decimal, pattern: str) -> str:
    key = pattern.strip().casefold()
    if key in {"", "general date"}:
        return date_text(value, pad_year=key == "general date")
    _refuse_half_second(value)
    moment = to_datetime(value, NEAREST_SECOND, shown=_settled_before_zero(value))
    named = _NAMED_DATE_FORMATS.get(key)
    if named is not None:
        if key == "long time":
            return f"{moment.hour % 12 or 12}:{moment.minute:02d}:{moment.second:02d} {'AM' if moment.hour < 12 else 'PM'}"
        if key == "medium time":
            return f"{moment.hour % 12 or 12:02d}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"
        pattern = named
    return _render_date_pattern(moment, pattern)


_DATE_CODE = re.compile(r"(?i)[dmyhnsqwc]|am/pm|a/p")
_NUMERIC_AS_DATE = re.compile(r"(?i)yy|dd|mm|hh|ss|am/pm|ttttt")


def _strip_literals(pattern: str) -> str:
    stripped = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", pattern)
    return stripped


def is_date_pattern(pattern: str, for_date_value: bool) -> bool:
    """Whether a FORMAT pattern is a date/time pattern (named date formats included)."""
    key = pattern.strip().casefold()
    if key in _NAMED_DATE_FORMATS:
        return True
    stripped = _strip_literals(pattern)
    if key in {"general number", "currency", "fixed", "standard", "percent", "scientific", "yes/no", "true/false", "on/off"}:
        return False
    if for_date_value:
        return bool(_DATE_CODE.search(stripped))
    # A number is formatted as a date/time when a date code comes before the first numeric placeholder
    # ("n" and "General" give minutes; "0 n" stays numeric).
    if _NUMERIC_AS_DATE.search(stripped) and not re.search(r"[0#]", stripped):
        return True
    for char in stripped:
        if char in "0#.":
            return False
        if char in "dmyhnsqwcDMYHNSQWC":
            return True
    return bool(_NUMERIC_AS_DATE.search(stripped))


def _render_date_pattern(moment: datetime, pattern: str) -> str:
    tokens = _date_tokens(pattern)
    has_ampm = any(kind == "ampm" for kind, _ in tokens)
    output: list[str] = []
    for index, (kind, text) in enumerate(tokens):
        if kind == "lit":
            output.append(text)
        elif kind == "ampm":
            suffix = "AM" if moment.hour < 12 else "PM"
            shown = suffix if (("/" in text and len(text) == 5) or len(text) == 4) else suffix[0]
            output.append(shown if text[0].isupper() else shown.lower())
        else:
            output.append(_date_field(moment, text, tokens, index, has_ampm))
    return "".join(output)


def _date_tokens(pattern: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == '"':
            end = pattern.find('"', index + 1)
            end = len(pattern) if end < 0 else end
            tokens.append(("lit", pattern[index + 1:end]))
            index = end + 1
        elif char == "\\" and index + 1 < len(pattern):
            tokens.append(("lit", pattern[index + 1]))
            index += 2
        elif char == "[":
            end = pattern.find("]", index)
            index = len(pattern) if end < 0 else end + 1  # [$-409] style locale tags have no visible effect
        elif pattern[index:index + 5].upper() == "AM/PM":
            tokens.append(("ampm", pattern[index:index + 5]))
            index += 5
        elif pattern[index:index + 4].upper() == "AMPM":
            tokens.append(("ampm", pattern[index:index + 4]))
            index += 4
        elif pattern[index:index + 3].upper() == "A/P":
            tokens.append(("ampm", pattern[index:index + 3]))
            index += 3
        elif char.lower() in "dmyhnsqwc":
            end = index
            while end < len(pattern) and pattern[end] == char:
                end += 1
            if char.lower() == "m" and end - index > 4:
                end = index + 4  # "mmmmm" is the month name followed by the month number
            tokens.append(("field", pattern[index:end]))
            index = end
        else:
            tokens.append(("lit", char))
            index += 1
    return tokens


def _previous_field(tokens: list[tuple[str, str]], index: int) -> str:
    position = index - 1
    while position >= 0:
        kind, text = tokens[position]
        if kind == "field":
            return text[0].lower()
        if kind == "lit" and text.strip(" :.") != "":
            return ""
        position -= 1
    return ""


def _date_field(moment: datetime, token: str, tokens: list[tuple[str, str]], index: int, has_ampm: bool) -> str:
    letter, width = token[0], len(token)
    lower = letter.lower()
    if lower == "d":
        if width == 1:
            return str(moment.day)
        if width == 2:
            return f"{moment.day:02d}"
        if width == 3:
            return _DAYS[moment.weekday()][:3]
        if width == 4:
            return _DAYS[moment.weekday()]
        return f"{moment.month}/{moment.day}/{moment.year}" if width == 5 else (
            f"{_DAYS[moment.weekday()]}, {_MONTHS[moment.month - 1]} {moment.day}, {moment.year}"
        )
    if lower == "m":
        if _previous_field(tokens, index) == "h":  # minutes follow an hour; anywhere else m is the month
            return f"{moment.minute:0{width}d}" if width > 1 else str(moment.minute)
        if width == 1:
            return str(moment.month)
        if width == 2:
            return f"{moment.month:02d}"
        return _MONTHS[moment.month - 1][:3] if width == 3 else _MONTHS[moment.month - 1]
    if lower == "y":
        day_of_year = str(moment.timetuple().tm_yday)
        if width == 1:
            return day_of_year
        if width == 2:
            return f"{moment.year % 100:02d}"
        if width == 3:
            return f"{moment.year % 100:02d}{day_of_year}"
        return f"{moment.year:04d}"
    if lower == "h":
        hour = moment.hour
        if has_ampm and (letter == "h" or any(text.upper() == "AMPM" for kind, text in tokens if kind == "ampm")):  # live: "H AMPM" is "6 PM"
            hour = hour % 12 or 12
        return f"{hour:0{width}d}" if width > 1 else str(hour)
    if lower == "n":
        return f"{moment.minute:0{width}d}" if width > 1 else str(moment.minute)
    if lower == "s":
        return f"{moment.second:0{width}d}" if width > 1 else str(moment.second)
    if lower == "q":
        return str((moment.month - 1) // 3 + 1)
    if lower == "w":
        return str(_weekday(moment, 1)) if width == 1 else str(_weeknum(moment, 1))
    if lower == "c":
        return date_text(from_datetime(moment))
    return token
