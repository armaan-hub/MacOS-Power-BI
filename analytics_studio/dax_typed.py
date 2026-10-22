"""DAX scalar value rules for text, True/False and non-finite numbers, read from Power BI Desktop 2.157.879.0.

Values are ``None`` (BLANK), ``bool``, ``Decimal`` (finite, ``Infinity``, ``-Infinity`` or ``NaN``) and ``str``.
Every rule here was compared against the live engine through ``tools/dax_battery_typed.json``; errors Power BI raises
are raised as ``MeasureRuntimeError`` so IFERROR can catch them.
"""

from __future__ import annotations

from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
import re

# Decimal arithmetic that yields NaN/Infinity instead of raising, like IEEE doubles.
QUIET = Context(prec=28, rounding=ROUND_HALF_EVEN, traps=[])
_INT64_LIMIT = 2**63
_NUMBER_TEXT = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


_CASE_KEEPS = {"\u00b5", "\u1e9e"}  # Power BI leaves micro sign and capital sharp s unchanged


def _simple_case(char: str, upper: bool) -> str:
    """Power BI maps text one character to one character (no "ß" -> "SS", "İ" -> "i" plus a combining dot)."""
    if char in _CASE_KEEPS:
        return char
    if char == "\u0130" and not upper:
        return "i"
    mapped = char.upper() if upper else char.lower()
    return mapped if len(mapped) == 1 else char


def _units(text: str) -> str:
    """Text as UTF-16 code units: every character above U+FFFF becomes its surrogate pair (Power BI counts 2 for it)."""
    if text.isascii():
        return text
    return "".join(
        chr(0xD800 + ((ord(c) - 0x10000) >> 10)) + chr(0xDC00 + ((ord(c) - 0x10000) & 0x3FF)) if ord(c) > 0xFFFF else c
        for c in text
    )


def _from_units(units: str) -> str:
    """Join surrogate pairs back into characters; a lone half stays a lone surrogate."""
    if units.isascii():
        return units
    return units.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _valid_unichar(code: int) -> bool:
    """UNICHAR refuses surrogates, noncharacters (U+FDD0..FDEF, U+xFFFE/xFFFF) and control characters other than tab/LF/CR."""
    if code < 32:
        return code in (9, 10, 13)
    return not (0xD800 <= code <= 0xDFFF or 0xFDD0 <= code <= 0xFDEF or (code & 0xFFFE) == 0xFFFE)


def _error(message: str) -> Exception:
    from .measures import MeasureRuntimeError  # imported late: measures imports this module

    return MeasureRuntimeError(message)


def type_name(value: object) -> str:
    if isinstance(value, bool):
        return "True/False"
    if isinstance(value, str):
        return "Text"
    return "Number"


def is_non_finite(value: object) -> bool:
    return isinstance(value, Decimal) and not value.is_finite()


def number_to_text(value: Decimal) -> str:
    """General number to text: whole numbers in full, otherwise 15 significant digits."""
    if value.is_nan():
        return "-nan(ind)"
    if value.is_infinite():
        return "-inf" if value < 0 else "inf"
    if value == value.to_integral_value() and abs(value) < _INT64_LIMIT:
        return str(int(value))
    sign = "-" if value < 0 else ""
    digits, exponent10 = _significant(abs(value))
    if exponent10 >= 15 or _decimal_places(digits, exponent10) > 15:
        mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        return f"{sign}{mantissa}E{'-' if exponent10 < 0 else '+'}{abs(exponent10):02d}"
    if exponent10 >= 0:
        whole = digits[: exponent10 + 1].ljust(exponent10 + 1, "0")
        fraction = digits[exponent10 + 1:]
        return f"{sign}{whole}" + (f".{fraction}" if fraction else "")
    return f"{sign}0.{'0' * (-exponent10 - 1)}{digits}"


def _significant(value: Decimal) -> tuple[str, int]:
    """(digits without trailing zeros, decimal exponent of the first digit) after rounding to 15 digits."""
    rounded = Context(prec=15, rounding=ROUND_HALF_EVEN, traps=[]).plus(value)
    _, digit_tuple, exponent = rounded.as_tuple()
    digits = "".join(map(str, digit_tuple)).rstrip("0") or "0"
    return digits, exponent + len(digit_tuple) - 1


def _decimal_places(digits: str, exponent10: int) -> int:
    return max(0, len(digits) - 1 - exponent10)


def to_text(value: object) -> str:
    """The text DAX produces when a value is concatenated or passed to a text function."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return value
    from . import dax_dates  # late import: dax_dates imports this module

    if dax_dates.is_date(value):
        return dax_dates.date_text(value)  # type: ignore[arg-type]
    return number_to_text(value)  # type: ignore[arg-type]


def text_to_number(text: str) -> Decimal:
    """VALUE / implicit text-to-number conversion: spaces, commas, a currency sign, (5) and 5- are accepted."""
    cleaned = text.strip().replace(",", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned, negative = cleaned[1:-1].strip(), True
    if cleaned.startswith("$"):
        cleaned = cleaned[1:].strip()
    if cleaned.endswith("-") and not cleaned.startswith(("-", "+")):
        cleaned, negative = cleaned[:-1].strip(), not negative
    if not _NUMBER_TEXT.match(cleaned):
        raise _error(f"Cannot convert value '{text}' of type Text to type Number.")
    number = Decimal(cleaned)
    return -number if negative else number


def to_number(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(1 if value else 0)
    if isinstance(value, str):
        return text_to_number(value)
    return value  # type: ignore[return-value]


def to_boolean(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raise _error(f"Cannot convert value '{value}' of type Text to type True/False.")
    return value != 0  # type: ignore[operator]


_ASTRAL = re.compile("[\U00010000-\U0010ffff]")


def text_key(text: str) -> str:
    """Case-insensitive comparison key: Power BI folds code units up to U+FFFF only, and joins adjacent surrogate halves."""
    if text.isascii():
        return text.casefold()
    text = _from_units(text)
    if not _ASTRAL.search(text):
        return text.casefold()
    return "".join(c if ord(c) > 0xFFFF else c.casefold() for c in text)


def compare(operator: str, left: object, right: object) -> bool:
    """DAX comparison: blank takes the other side's type, text ignores case, mixed types are an error."""
    if left is None and right is None:
        left, right = Decimal(0), Decimal(0)
    elif left is None:
        left = _blank_like(right)
    elif right is None:
        right = _blank_like(left)
    if isinstance(left, bool) != isinstance(right, bool) or isinstance(left, str) != isinstance(right, str):
        raise _error(
            "DAX comparison operations do not support comparing values of type "
            f"{type_name(left)} with values of type {type_name(right)}."
        )
    if isinstance(left, str):
        a, b = text_key(left), text_key(right)  # type: ignore[arg-type]
    elif isinstance(left, bool):
        a, b = int(left), int(right)  # type: ignore[arg-type]
    else:
        a, b = left, right
        if a.is_nan() or b.is_nan():  # type: ignore[union-attr]
            return operator == "<>"
    if operator == "=":
        return a == b
    if operator == "<>":
        return a != b
    if operator == "<":
        return a < b  # type: ignore[operator]
    if operator == "<=":
        return a <= b  # type: ignore[operator]
    if operator == ">":
        return a > b  # type: ignore[operator]
    return a >= b  # type: ignore[operator]


def _blank_like(other: object) -> object:
    if isinstance(other, bool):
        return False
    if isinstance(other, str):
        return ""
    return Decimal(0)


def values_match(left: object, right: object) -> bool:
    """SWITCH matching: blank only equals blank, text ignores case, True/False never equals a number or text."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool) or isinstance(left, str) != isinstance(right, str):
        raise _error(f"SWITCH cannot compare {type_name(left)} with {type_name(right)}.")
    return compare("=", left, right)


def whole(value: object, function: str, *, minimum: int | None = None) -> int:
    """A count argument: blank is 0, fractions round to the nearest whole number (half away from zero)."""
    number = to_number(value)
    if not number.is_finite():
        raise _error(f"An argument of function '{function}' has the wrong data type or has an invalid value.")
    count = int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if minimum is not None and count < minimum:
        raise _error(f"An argument of function '{function}' has the wrong data type or has an invalid value.")
    return count


def text_function(function: str, args: list[object]) -> object:
    """Text functions whose arguments are already evaluated; returns the DAX result (None is BLANK)."""
    if function == "CONCATENATE":
        if args[0] is None and args[1] is None:
            return None
        return to_text(args[0]) + to_text(args[1])
    if function == "EXACT":
        return to_text(args[0]) == to_text(args[1])
    if function == "REPT":
        if args[0] is None:
            return None
        text = to_text(args[0])
        return text * whole(args[1], function, minimum=0)
    if function == "UNICHAR":
        code = whole(args[0], function, minimum=1)
        if code > 0x10FFFF or not _valid_unichar(code):
            raise _error("An argument of function 'UNICHAR' has the wrong data type or has an invalid value.")
        return chr(code)
    if function == "FIXED":
        return _fixed(args)
    if function in {"FIND", "SEARCH"}:
        if len(args) > 2 and args[2] is None:
            raise _error(f"An argument of function '{function}' has the wrong data type or the result is too large or too small.")
        if function == "SEARCH" and args[0] is None and args[1] is None:
            raise _error("The search Text provided to function 'SEARCH' could not be found in the given text.")
        return _find(function, args, "")
    first = args[0]
    if function == "VALUE":
        if first is None:
            return None
        return Decimal(first) if isinstance(first, Decimal) else text_to_number(to_text(first))
    if first is None:
        return None
    text = _units(to_text(first))  # Power BI positions and lengths are UTF-16 code units
    if function == "LEN":
        return Decimal(len(text))
    if function == "UPPER":
        return _from_units("".join(_simple_case(c, True) for c in text))
    if function == "LOWER":
        return _from_units("".join(_simple_case(c, False) for c in text))
    if function == "TRIM":
        return _from_units(" ".join(part for part in text.split(" ") if part))
    if function == "UNICODE":
        if not text:
            return None
        if 0xD800 <= ord(text[0]) <= 0xDBFF:  # a high surrogate must be followed by its low half
            if len(text) < 2 or not 0xDC00 <= ord(text[1]) <= 0xDFFF:
                raise _error("An argument of function 'UNICODE' has the wrong data type or has an invalid value.")
            return Decimal(ord(_from_units(text[:2])))
        return Decimal(ord(text[0]))
    if function in {"LEFT", "RIGHT"}:
        count = whole(args[1], function, minimum=0) if len(args) > 1 else 1
        return _from_units(text[:count] if function == "LEFT" else (text[len(text) - count:] if count else ""))
    if function == "MID":
        start = whole(args[1], function, minimum=1)
        count = whole(args[2], function, minimum=0)
        return _from_units(text[start - 1:start - 1 + count])
    if function == "SUBSTITUTE":
        old, new = _units(to_text(args[1])), _units(to_text(args[2]))
        if not old:
            return _from_units(text)
        if len(args) < 4 or args[3] is None:
            replaced = text.replace(old, new)
            return None if args[2] is None and not replaced else _from_units(replaced)
        instance = whole(args[3], function, minimum=1)
        position = -1
        for _ in range(instance):
            position = text.find(old, position + 1)
            if position < 0:
                return _from_units(text)
        return _from_units(text[:position] + new + text[position + len(old):])
    if function == "REPLACE":
        start = whole(args[1], function, minimum=1)
        count = whole(args[2], function, minimum=0)
        return _from_units(text[:start - 1] + _units(to_text(args[3])) + text[start - 1 + count:])
    if function in {"FIND", "SEARCH"}:
        return _find(function, args, text)
    raise _error(f"Function {function} is not supported by the local DAX engine.")


def _find(function: str, args: list[object], within_text: str) -> object:
    """FIND(find, within[, start[, notfound]]) and SEARCH (case-insensitive, ? * ~ wildcards), in UTF-16 code units."""
    needle = _units(to_text(args[0]))
    haystack = _units(to_text(args[1])) if len(args) > 1 else ""
    start = whole(args[2], function, minimum=1) if len(args) > 2 and args[2] is not None else 1
    not_found = _MISSING
    if len(args) > 3:  # the result is a number, so the NotFoundValue must convert to one
        not_found = None if args[3] is None else Decimal(whole(args[3], function))
    if not needle:  # an empty needle is found at 1 provided the start lies inside the text (SEARCH refuses empty text)
        if start > max(len(haystack), 1) or (function == "SEARCH" and not haystack):
            raise _error(f"The search Text provided to function '{function}' could not be found in the given text.")
        return Decimal(1)
    if start > len(haystack):
        found = -1
    elif function == "FIND":
        found = haystack.find(needle, start - 1)
    else:
        found = _wildcard_find(needle, haystack, start - 1)
    if found < 0:
        if not_found is _MISSING:
            raise _error(f"The search Text provided to function '{function}' could not be found in the given text.")
        return not_found
    return Decimal(found + 1)


_MISSING = object()


def _wildcard_find(needle: str, haystack: str, start: int) -> int:
    pattern = []
    index = 0
    while index < len(needle):
        char = needle[index]
        if char == "~" and index + 1 < len(needle):
            index += 1
            pattern.append(re.escape(needle[index]))
        elif char == "?":
            pattern.append(".")
        elif char == "*":
            pattern.append(".*?")
        else:
            pattern.append(re.escape(char))
        index += 1
    match = re.compile("".join(pattern), re.IGNORECASE | re.DOTALL).search(haystack, start)
    return -1 if match is None else match.start()


def _fixed(args: list[object]) -> str:
    number = to_number(args[0])
    decimals = whole(args[1], "FIXED") if len(args) > 1 and args[1] is not None else 2
    no_commas = to_boolean(args[2]) if len(args) > 2 else False
    if not number.is_finite():
        return number_to_text(number)
    quantum = Decimal(1).scaleb(-decimals)
    with_context = Context(prec=60, rounding=ROUND_HALF_UP, traps=[])
    rounded = with_context.quantize(number, quantum) if decimals >= 0 else (
        with_context.quantize(number, Decimal(1).scaleb(-decimals)).quantize(Decimal(1))
    )
    text = f"{rounded:{'' if no_commas else ','}.{max(decimals, 0)}f}"
    return text
