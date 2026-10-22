"""DAX bit, cotangent, string-search, path, NETWORKDAYS, YEARFRAC and type-test functions, matching Power BI Desktop 2.157.879.0.

Scalar functions take already-evaluated arguments (``None`` is BLANK).  Compared live through
``tools/dax_battery_misc.json``.  Not implemented (the app then refuses the call instead of answering wrongly):

* ``ISINTEGER`` / ``ISINT64`` / ``ISDOUBLE`` / ``ISDECIMAL`` / ``ISCURRENCY``: Power BI answers from the static data
  type of the expression (``2.0`` is a double, ``5/5`` is a double, ``FLOOR(2.5,1)`` an integer, ``CURRENCY(2)`` a
  currency), which a value cannot carry.
* ``PATH`` (needs the ID and parent columns of a table), ``NAMEOF`` (needs a column, measure or table reference),
  ``TOCSV`` / ``TOJSON`` (table functions) and the holidays table of ``NETWORKDAYS``.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
import math
import re
import unicodedata

from analytics_studio import dax_dates, dax_typed

ARITY: dict[str, tuple[int, int]] = {
    "BITAND": (2, 2), "BITOR": (2, 2), "BITXOR": (2, 2), "BITLSHIFT": (2, 2), "BITRSHIFT": (2, 2),
    "COT": (1, 1), "COTH": (1, 1), "ACOT": (1, 1), "ACOTH": (1, 1),
    "CONTAINSSTRING": (2, 2), "CONTAINSSTRINGEXACT": (2, 2),
    "PATHCONTAINS": (2, 2), "PATHITEM": (2, 3), "PATHITEMREVERSE": (2, 3), "PATHLENGTH": (1, 1),
    "NETWORKDAYS": (2, 3), "YEARFRAC": (2, 3), "USERCULTURE": (0, 0),
    "ISBOOLEAN": (1, 1), "ISSTRING": (1, 1), "ISNUMERIC": (1, 1), "ISDATETIME": (1, 1),
}
CATEGORY: dict[str, str] = {
    **dict.fromkeys(
        ["CONTAINSSTRING", "CONTAINSSTRINGEXACT", "PATHCONTAINS", "ISBOOLEAN", "ISSTRING", "ISNUMERIC", "ISDATETIME"],
        "boolean",
    ),
    **dict.fromkeys(["PATHITEM", "PATHITEMREVERSE", "USERCULTURE"], "text"),
}

_INT64 = 2**63
_DBL_MIN = 2.2250738585072014e-308
_TOO_BIG = "The result of a conversion or arithmetic operation is either too large or too small."
_WRONG = "An argument of function '{}' has the wrong data type or the result is too large or too small."
_DIVISION = "Division by zero has occurred when evaluating function '{}'."


def _error(message: str) -> Exception:
    return dax_typed._error(message)


def _decimal(value: object) -> Decimal:
    number = dax_typed.to_number(value)
    return Decimal(number)


# ------------------------------------------------------------------------------------------------ BIT functions


def _int64(value: object, *, blank: int | None = 0) -> int:
    """A bit-function operand: blank is ``blank``, fractions round half away from zero (through a double)."""
    number = _decimal(value)
    if not number.is_finite():
        raise _error(_TOO_BIG)
    if number != number.to_integral_value():
        number = Decimal(float(number))
    result = int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP, context=dax_typed.QUIET.copy()))
    if not -_INT64 < result < _INT64:  # int64 minimum is refused too (a double -2^63 does not convert)
        raise _error(_TOO_BIG)
    return result


def _wrap(value: int) -> int:
    return (value + _INT64) % (2 * _INT64) - _INT64


def _bit_function(function: str, args: list[object]) -> object:
    first, second = args
    if function == "BITAND" and (first is None or second is None):
        # BITAND validates the other operand first, then answers BLANK
        for value in args:
            if value is not None:
                _int64(value)
        return None
    if first is None and second is None:
        return None
    if function in {"BITLSHIFT", "BITRSHIFT"} and first is None:
        if second is not None:
            _int64(second)
        return None
    a, b = _int64(first), _int64(second)
    if function == "BITAND":
        return Decimal(a & b)
    if function == "BITOR":
        return Decimal(a | b)
    if function == "BITXOR":
        return Decimal(a ^ b)
    left = (function == "BITLSHIFT") == (b >= 0)
    amount = abs(b) % 64
    return Decimal(_wrap(a << amount) if left else a >> amount)


# ---------------------------------------------------------------------------------------------- cotangents


_SQRT_HALF = math.sqrt(0.5)
_OCTANT_SIN = (0.0, _SQRT_HALF, 1.0, _SQRT_HALF, 0.0, -_SQRT_HALF, -1.0, -_SQRT_HALF)
_OCTANT_COS = (1.0, _SQRT_HALF, 0.0, -_SQRT_HALF, -1.0, -_SQRT_HALF, 0.0, _SQRT_HALF)
_QUARTER_PI = math.pi / 4


def _cot_value(x: float, function: str) -> float:
    """Cotangent the way Power BI's engine computes it.

    The argument is reduced by whole multiples of the *double* pi/4 (so COT(3.14159265358979) sees the double pi, not
    the real one) and, at an exact multiple of pi/4 (x / (pi/4) is a whole number), the engine picks the wrong octant
    for k mod 8 in {1, 3, 4, 6}: COT(PI()) = 1, COT(PI()/4) is a division by zero.  Verified for k up to 1000.
    Arguments above about 3E+6 lose accuracy in the engine's own reduction, which is not reproduced."""
    magnitude = abs(x)
    ratio = magnitude / _QUARTER_PI
    if ratio == math.floor(ratio):
        k = int(ratio)
        octant = (k + 1 if k % 8 in (1, 3, 4, 6) else k) % 8
        sine, cosine = _OCTANT_SIN[octant], _OCTANT_COS[octant]
        if sine == 0 or cosine == 0:
            raise _error(_DIVISION.format(function))
        return (cosine / sine) * (1 if x > 0 else -1)
    octant_count = math.floor(ratio)
    octant = int(octant_count % 8)
    if octant & 1:
        octant += 1
        octant_count += 1
    reduced = math.tan(magnitude - octant_count * _QUARTER_PI)
    if reduced == 0:
        raise _error(_DIVISION.format(function))
    return (-reduced if octant & 2 else 1 / reduced) * (1 if x > 0 else -1)


def _to_float(value: object) -> float:
    number = _decimal(value)
    if number.is_nan():
        return math.nan
    try:
        return float(number)
    except OverflowError:
        return math.inf if number > 0 else -math.inf


def _double(value: float) -> Decimal:
    return Decimal(repr(value)) if value != 0 else Decimal(0)


def _cotangent(function: str, args: list[object]) -> Decimal:
    x = _to_float(args[0])
    if function == "COT":
        if not math.isfinite(x) or abs(x) >= 2**27:
            raise _error(_WRONG.format(function))
        if abs(x) < _DBL_MIN:
            raise _error(_DIVISION.format(function))
        return _double(_cot_value(x, function))
    if function == "COTH":
        if not math.isfinite(x):
            return Decimal(0)
        if abs(x) < _DBL_MIN:
            raise _error(_DIVISION.format(function))
        return _double(1 / math.tanh(x))
    if function == "ACOT":
        if math.isnan(x):
            return _double(math.pi)
        if math.isinf(x):
            return Decimal(0) if x > 0 else _double(math.pi)
        number = _decimal(args[0])
        if x == 0 and not (number.is_signed() and number == 0):
            return _double(math.pi / 2)
        if x == 0:
            return _double(math.pi)
        if abs(x) < _DBL_MIN:
            return Decimal(0) if x > 0 else _double(math.pi)
        return _double(math.atan(1 / x) if x > 0 else math.pi + math.atan(1 / x))
    # ACOTH
    if not math.isfinite(x):
        return Decimal(0)
    if abs(x) <= 1:
        raise _error(_WRONG.format(function))
    value = 0.5 * math.log1p(2 / (abs(x) - 1))
    return _double(value if x > 0 else -value)


# ---------------------------------------------------------------------------------------------- text search

_IGNORABLE = dict.fromkeys(map(ord, "­‍⁠‎"))
_EXPANSIONS = {
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ĳ": "ij", "Ĳ": "IJ", "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}


def _fold(text: str) -> str:
    """The comparison key of the ignore-case search: width, kana type, ligatures and case do not matter."""
    out: list[str] = []
    for ch in text.translate(_IGNORABLE):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = chr(code - 0xFEE0)
        elif 0xFF61 <= code <= 0xFF9F:
            ch = unicodedata.normalize("NFKC", ch)
        if 0x30A1 <= ord(ch[0]) <= 0x30F6 and len(ch) == 1:
            ch = chr(ord(ch) - 0x60)
        out.append(_EXPANSIONS.get(ch, ch))
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", "".join(out)).casefold())


def _found(text: str, needle: str) -> bool:
    """Substring search that never ends inside a character (a following combining mark belongs to the match)."""
    start = text.find(needle)
    while start >= 0:
        end = start + len(needle)
        if needle == "" or end >= len(text) or not unicodedata.category(text[end]).startswith("M"):
            return True
        start = text.find(needle, start + 1)
    return False


def _contains_exact(haystack: str, needle: str) -> bool:
    """Case-sensitive search: soft hyphens and similar are ignored and combining marks compose in the text searched;
    a ligature or sharp s in the searched-for text also matches its expansion."""
    text = unicodedata.normalize("NFC", haystack.translate(_IGNORABLE))
    variants = {needle, "".join(_EXPANSIONS.get(ch, ch) for ch in needle)}
    return any(_found(text, variant) for variant in variants)


def _contains_string(function: str, args: list[object]) -> bool:
    text, find = dax_typed.to_text(args[0]), dax_typed.to_text(args[1])
    if function == "CONTAINSSTRINGEXACT":
        return _contains_exact(text, find)
    if text == "":
        return False  # a blank or empty text contains nothing, not even the empty text
    folded = _fold(text)
    if "*" not in find and "?" not in find:
        return _found(folded, _fold(find))
    return _wildcard_search(find, folded) is not None


def _wildcard_search(find: str, folded_text: str) -> object:
    """SEARCH-style matching: ? is any one character, * any run, ~ makes the next character literal."""
    pattern: list[str] = []
    literal: list[str] = []

    def flush() -> None:
        if literal:
            pattern.append(re.escape(_fold("".join(literal))))
            literal.clear()

    index = 0
    while index < len(find):
        char = find[index]
        if char == "~" and index + 1 < len(find):
            index += 1
            literal.append(find[index])
        elif char in "?*":
            flush()
            pattern.append("." if char == "?" else ".*?")
        else:
            literal.append(char)
        index += 1
    flush()
    return re.compile("".join(pattern), re.DOTALL).search(folded_text)


# --------------------------------------------------------------------------------------------------- paths


def _item_position(value: object) -> int:
    number = _decimal(value)
    if not number.is_finite():
        raise _error(_TOO_BIG)
    result = int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP, context=dax_typed.QUIET.copy()))
    if not -_INT64 < result < _INT64:
        raise _error(_TOO_BIG)
    return result


def _item_type(args: list[object]) -> int:
    if len(args) < 3:
        return 0
    value = args[2]
    if isinstance(value, bool) or not isinstance(value, Decimal) or dax_dates.is_date(value) or value not in (0, 1):
        raise _error(
            "The final argument to the PathItem or PathItemReverse functions should be 0 for TEXT or 1 for INTEGER. "
            "It is also possible to use words 'TEXT' and 'INTEGER' respectively."
        )
    return int(value)


def _path_integer(item: str) -> Decimal:
    """PATHITEM type INTEGER: the item read as a number and rounded half to even."""
    if not item.isascii():
        raise _error("The following system error occurred: Type mismatch.")
    try:
        number = dax_typed.text_to_number(item)
    except Exception as exc:  # the conversion failure is Power BI's "Type mismatch"
        raise _error("The following system error occurred: Type mismatch.") from exc
    result = int(number.quantize(Decimal(1), rounding=ROUND_HALF_EVEN, context=dax_typed.QUIET.copy()))
    if not -_INT64 <= result < _INT64:
        raise _error("The following system error occurred: Out of present range.")
    return Decimal(result)


def _path_function(function: str, args: list[object]) -> object:
    if function == "PATHLENGTH":
        return None if args[0] is None else Decimal(dax_typed.to_text(args[0]).count("|") + 1)
    if function == "PATHCONTAINS":
        if args[0] is None or args[1] is None:
            return False
        key = _fold(dax_typed.to_text(args[1]))
        return any(_fold(item) == key for item in dax_typed.to_text(args[0]).split("|"))
    position = _item_position(args[1])
    kind = _item_type(args)
    if args[0] is None:
        return None
    items = dax_typed.to_text(args[0]).split("|")
    index = position if function == "PATHITEM" else len(items) - position + 1
    if position < 1 or index < 1 or index > len(items):
        return None
    item = items[index - 1]
    return _path_integer(item) if kind == 1 else item


# -------------------------------------------------------------------------------------- calendar and dates

_MAX_SERIAL = 2958465  # 9999-12-31
_TIME_ONLY = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?(\s*[AaPp][Mm])?\s*$")


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Serial (0 = 1899-12-30) of a proleptic Gregorian date; works for any year."""
    year -= month <= 2
    era = year // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468 + 25569


def _civil_from_days(serial: int) -> tuple[int, int, int]:
    z = serial - 25569 + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    return year + (month <= 2), month, day


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    return 29 if month == 2 and _is_leap(year) else (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]


def _serial(value: object, function: str) -> int:
    """A date argument as a whole serial: blank is 0, any Boolean is 1, text must read as a date, the time is dropped."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1
    if isinstance(value, str):
        if _TIME_ONLY.match(value):
            return 0
        number = Decimal(dax_dates.parse_date_text(value))
    else:
        number = Decimal(value)  # type: ignore[arg-type]
    if not number.is_finite():
        raise _error(_WRONG.format(function))
    day = int(number.to_integral_value(rounding="ROUND_FLOOR"))
    if day > _MAX_SERIAL:
        raise _error(_WRONG.format(function))
    return day


def _whole_argument(value: object, function: str) -> int:
    number = _decimal(value)
    if not number.is_finite():
        raise _error(_WRONG.format(function))
    return int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP, context=dax_typed.QUIET.copy()))


def _thirty_360(start: int, end: int, european: bool) -> int:
    y1, m1, d1 = _civil_from_days(start)
    y2, m2, d2 = _civil_from_days(end)
    if european:
        d1, d2 = min(d1, 30), min(d2, 30)
    else:
        last_feb_1 = m1 == 2 and d1 == _days_in_month(y1, 2)
        last_feb_2 = m2 == 2 and d2 == _days_in_month(y2, 2)
        if d2 == 31 and d1 >= 30:
            d2 = 30
        if last_feb_1 and last_feb_2:
            d2 = 30
        if last_feb_1:
            d1 = 30
        if d1 == 31:
            d1 = 30
    return (y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)


def _actual_actual_year(start: int, end: int) -> float:
    y1, m1, d1 = _civil_from_days(start)
    y2, m2, d2 = _civil_from_days(end)
    if y1 == y2:
        return 366.0 if _is_leap(y1) else 365.0
    if y2 == y1 + 1 and (m1 > m2 or (m1 == m2 and d1 >= d2)):
        in_range = (_is_leap(y1) and start <= _days_from_civil(y1, 2, 29)) or (
            _is_leap(y2) and end >= _days_from_civil(y2, 2, 29)
        )
        return 366.0 if in_range else 365.0
    total = sum(366 if _is_leap(year) else 365 for year in range(y1, y2 + 1))
    return total / (y2 - y1 + 1)


def _yearfrac(args: list[object]) -> object:
    if args[0] is None and args[1] is None:
        basis_check = None if len(args) < 3 else args[2]
        if basis_check is not None:
            _whole_argument(basis_check, "YEARFRAC")
        return None
    start, end = _serial(args[0], "YEARFRAC"), _serial(args[1], "YEARFRAC")
    basis = 0 if len(args) < 3 or args[2] is None else _whole_argument(args[2], "YEARFRAC")
    if basis not in range(5):
        raise _error(_WRONG.format("YEARFRAC"))
    start, end = min(start, end), max(start, end)
    if basis == 0 or basis == 4:
        return _double(_thirty_360(start, end, basis == 4) / 360)
    if basis == 1:
        return _double((end - start) / _actual_actual_year(start, end))
    return _double((end - start) / (360 if basis == 2 else 365))


_WEEKEND_DAYS = {  # weekday numbers with Monday = 0
    1: (5, 6), 2: (6, 0), 3: (0, 1), 4: (1, 2), 5: (2, 3), 6: (3, 4), 7: (4, 5),
    11: (6,), 12: (0,), 13: (1,), 14: (2,), 15: (3,), 16: (4,), 17: (5,),
}


def _workdays_up_to(serial: int, weekend: tuple[int, ...]) -> int:
    """Working days among the serials 0 .. serial-1 (serial 0 is a Saturday, so weekday = (serial + 5) % 7, Monday 0)."""
    weeks, rest = divmod(serial, 7)
    total = weeks * (7 - len(weekend))
    first = 5  # weekday of serial 0
    return total + sum(1 for offset in range(rest) if (first + offset) % 7 not in weekend)


def _networkdays(args: list[object]) -> object:
    code = 1 if len(args) < 3 else _whole_argument(args[2], "NETWORKDAYS")
    if code not in _WEEKEND_DAYS:
        raise _error("The third argument of NETWORKDAYS function (Weekend) can only be 1 ~ 7 or 11 ~ 17.")
    if args[0] is None and args[1] is None:
        return None
    start, end = _serial(args[0], "NETWORKDAYS"), _serial(args[1], "NETWORKDAYS")
    weekend = _WEEKEND_DAYS[code]
    low, high = min(start, end), max(start, end)
    # the serials are offset so that the arithmetic never sees a negative number
    shift = 7 * ((-low) // 7 + 1) if low < 0 else 0
    count = _workdays_up_to(high + shift + 1, weekend) - _workdays_up_to(low + shift, weekend)
    return Decimal(count if start <= end else -count)


# --------------------------------------------------------------------------------------------------- entry


def call(function: str, args: list[object]) -> object:
    if function in {"BITAND", "BITOR", "BITXOR", "BITLSHIFT", "BITRSHIFT"}:
        return _bit_function(function, args)
    if function in {"COT", "COTH", "ACOT", "ACOTH"}:
        return _cotangent(function, args)
    if function in {"CONTAINSSTRING", "CONTAINSSTRINGEXACT"}:
        return _contains_string(function, args)
    if function in {"PATHCONTAINS", "PATHITEM", "PATHITEMREVERSE", "PATHLENGTH"}:
        return _path_function(function, args)
    if function == "YEARFRAC":
        return _yearfrac(args)
    if function == "NETWORKDAYS":
        return _networkdays(args)
    if function == "USERCULTURE":
        return "en-US"
    value = args[0]
    if function == "ISBOOLEAN":
        return isinstance(value, bool)
    if function == "ISSTRING":
        return isinstance(value, str)
    if function == "ISNUMERIC":
        return isinstance(value, Decimal) and not dax_dates.is_date(value)
    if function == "ISDATETIME":
        return dax_dates.is_date(value)
    raise KeyError(function)
