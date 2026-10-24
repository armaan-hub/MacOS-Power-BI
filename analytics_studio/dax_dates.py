"""DAX date/time values and functions, matching Power BI Desktop 2.157.879.0 (en-US).

A DateTime is a number of days since 1899-12-30 with a "date" tag (``DaxDateTime``), so arithmetic, comparisons and
``INT``/``VALUE`` work on the number while ``&``, ``FORMAT`` and the display use date text.  Compared live through
``tools/dax_battery_typed.json`` and the date columns of the standing test workbook.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP
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


def to_datetime(serial: Decimal, rounding: str = ROUND_HALF_UP) -> datetime:
    if not serial.is_finite():
        raise dax_typed._error("An argument has the wrong data type or the result is too large or too small.")
    days = serial.to_integral_value(rounding=ROUND_FLOOR)
    if serial < 0 and serial != days:
        # live Power BI counts the time of day of a serial before day zero forward from the day it follows (OLE) and rounds it in a
        # way that is not modelled here (iteration 84, 800 probes): refused rather than guessed
        raise dax_typed._error("A time of day before December 30, 1899 is not supported in the local engine.")
    scaled = (serial - days) * _SECONDS_PER_DAY
    if rounding == ROUND_DOWN:
        seconds = scaled.quantize(Decimal(1), rounding=ROUND_DOWN)
    elif rounding == NEAREST_SECOND:  # live Power BI: WEEKDAY / WEEKNUM take the day of the time of day rounded to the nearest second
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


def date_text(value: Decimal, pad_year: bool = False) -> str:
    """The text of a date in a concatenation: M/d/yyyy, plus h:mm:ss AM/PM when there is a time of day (FORMAT "General Date" pads the
    year to four digits, a concatenation does not: live Power BI, 1/1/0100 and 1/1/100)."""
    moment = to_datetime(value, NEAREST_SECOND)  # live Power BI: the text of a date shows the time of day rounded to the nearest second
    time_text = f"{moment.hour % 12 or 12}:{moment.minute:02d}:{moment.second:02d} {'AM' if moment.hour < 12 else 'PM'}"
    if (moment.year, moment.month, moment.day) == (1899, 12, 30):
        return time_text  # day zero is a time of day only
    text = f"{moment.month}/{moment.day}/{moment.year:04d}" if pad_year else f"{moment.month}/{moment.day}/{moment.year}"
    if moment.hour or moment.minute or moment.second:
        text += " " + time_text
    return text


def oracle_text(value: Decimal) -> str:
    """The text Power BI's ADOMD client shows for a DateTime result (used by the comparison harness)."""
    return to_datetime(value).strftime("%m/%d/%Y %H:%M:%S")


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


def _moment(value: object, rounding: str = ROUND_HALF_UP) -> datetime | None:
    """A date argument: a DateTime or number, or text that reads as a date; blank gives None."""
    if value is None:
        return None
    if isinstance(value, str):
        return to_datetime(parse_date_text(value), rounding)
    if isinstance(value, bool):
        return to_datetime(Decimal(int(value)), rounding)
    return to_datetime(value, rounding)  # type: ignore[arg-type]


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
    moment = _moment(args[0], ROUND_FLOOR if function in {"HOUR", "MINUTE", "SECOND"} else NEAREST_SECOND if function in {"WEEKDAY", "WEEKNUM"} else ROUND_HALF_UP)
    if moment is None:
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
    moment = to_datetime(value, NEAREST_SECOND)
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
