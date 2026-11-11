"""DAX scalar value rules for text, True/False and non-finite numbers, read from Power BI Desktop 2.157.879.0.

Values are ``None`` (BLANK), ``bool``, ``Decimal`` (finite, ``Infinity``, ``-Infinity`` or ``NaN``) and ``str``.
Every rule here was compared against the live engine through ``tools/dax_battery_typed.json``; errors Power BI raises
are raised as ``MeasureRuntimeError`` so IFERROR can catch them.
"""

from __future__ import annotations

from typing import Callable
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
import contextlib
import math
import re
import sys
import unicodedata

# Decimal arithmetic that yields NaN/Infinity instead of raising, like IEEE doubles.
QUIET = Context(prec=28, rounding=ROUND_HALF_EVEN, traps=[])
_INT64_LIMIT = 2**63
DOUBLE_EXPONENT_FROM = Decimal(10) ** 15  # a Double this big or bigger prints with an exponent, as Power BI does
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
    data = text.encode("utf-16-le", "surrogatepass")
    return "".join(map(chr, memoryview(data).cast("H")))


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


def refusal(message: str) -> Exception:
    """The local engine has no answer: not an error of the expression, so IFERROR must not turn it into a value."""
    from .measures import MeasureError  # imported late: measures imports this module

    return MeasureError(message)


def type_name(value: object) -> str:
    if isinstance(value, bool):
        return "True/False"
    if isinstance(value, str):
        return "Text"
    return "Number"


def is_non_finite(value: object) -> bool:
    return isinstance(value, Decimal) and not value.is_finite()


def number_to_text(value: Decimal, double: bool = False) -> str:
    """General number to text: whole numbers in full, otherwise 15 significant digits. A Double of 1E15 or more uses an exponent."""
    if value.is_nan():
        return "-nan(ind)" if value.is_signed() else "nan"  # Part B: the sign of a NaN shows in text
    if value.is_infinite():
        return "-inf" if value < 0 else "inf"
    if value == value.to_integral_value() and -_INT64_LIMIT <= value < _INT64_LIMIT and not (double and abs(value) >= DOUBLE_EXPONENT_FROM):  # Part C: -2^63 is a whole Int64 (a wrapped sum)
        return str(int(value))
    sign = "-" if value < 0 else ""
    digits, exponent10 = _significant(abs(value))
    below_1e15 = abs(value) < DOUBLE_EXPONENT_FROM and exponent10 == 15  # Part C: a magnitude below 1E15 whose 15-digit rounding reaches 1E15 stays in fixed notation ((0.1-1E15)&"z" is -1000000000000000z, measured)
    if (exponent10 >= 15 and not below_1e15) or _decimal_places(digits, exponent10) > 15:
        mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        return f"{sign}{mantissa}E{'-' if exponent10 < 0 else '+'}{abs(exponent10):02d}"
    if exponent10 >= 0:
        whole = digits[: exponent10 + 1].ljust(exponent10 + 1, "0")
        fraction = digits[exponent10 + 1:]
        return f"{sign}{whole}" + (f".{fraction}" if fraction else "")
    return f"{sign}0.{'0' * (-exponent10 - 1)}{digits}"


def _significant(value: Decimal) -> tuple[str, int]:
    """(digits without trailing zeros, decimal exponent of the first digit) after rounding to 15 digits."""
    try:
        exact = Decimal(float(value))  # Power BI rounds the exact binary value of the Double, half away from zero (live Power BI, Task 20)
    except OverflowError:
        exact = value
    if exact == 0 and value != 0:
        exact = value  # below the Double range: nothing binary to take
    fifteen = Context(prec=15, rounding=ROUND_HALF_UP, traps=[])
    rounded = fifteen.plus(exact)
    if value.is_finite() and value != 0 and not Decimal("1E-100") < abs(value) < Decimal("1E100") and len(value.as_tuple().digits) > 17 and fifteen.plus(value) != rounded:
        # this far out the binary operands of a division are not exact, so the digits held here and the Double differ and the last digit cannot be told
        raise refusal("The last digit of a Double this far from 1 is not modelled by the local engine.")
    _, digit_tuple, exponent = rounded.as_tuple()
    digits = "".join(map(str, digit_tuple)).rstrip("0") or "0"
    return digits, exponent + len(digit_tuple) - 1


def _decimal_places(digits: str, exponent10: int) -> int:
    return max(0, len(digits) - 1 - exponent10)


# the positions of the arguments a text function reads as text, where a number becomes text implicitly
TEXT_ARGUMENTS = {
    "LEFT": (0,), "RIGHT": (0,), "MID": (0,), "LEN": (0,), "UPPER": (0,), "LOWER": (0,), "TRIM": (0,), "UNICODE": (0,), "REPT": (0,),
    "SUBSTITUTE": (0, 1, 2), "REPLACE": (0, 3), "CONCATENATE": (0, 1), "EXACT": (0, 1), "FIND": (0, 1), "SEARCH": (0, 1),
    "CONTAINSSTRING": (0, 1), "CONTAINSSTRINGEXACT": (0, 1),
}


def to_text(value: object, double: bool = False) -> str:
    """The text DAX produces when a value is concatenated or passed to a text function; double: the value is a Double."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        return value
    from . import dax_dates  # late import: dax_dates imports this module

    if dax_dates.is_date(value):
        return dax_dates.date_text(value)  # type: ignore[arg-type]
    return number_to_text(value, double)  # type: ignore[arg-type]


def currency_text(value: Decimal) -> str:
    """Part D: a Currency as text keeps its four decimals, trailing zeros dropped (-844674407370955.1616, 776627963145224.192, 2)."""
    if value.is_zero():
        return "0"  # a Currency has no sign of zero
    text = format(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


_SUBNORMAL_OK = False
_TINY_TEXT = 1e-300  # a text whose double is smaller than this (and not zero) is the tiny text of Task 74
DBL_MIN = Decimal("2.2250738585072014E-308")  # smallest positive normal IEEE double; 0 < |x| < DBL_MIN is subnormal
DBL_MIN_FLOAT = 2.2250738585072014e-308


@contextlib.contextmanager
def subnormal_text_allowed():
    """Task 74: the operators + - * and the functions ABS, VALUE and LN answer a subnormal text (all four held-out grids agree with the double);
    every other function and operator refuses it (SIGN, DIVIDE, POWER, MOD, INT ... treat it as a zero or not, by no rule found)."""
    global _SUBNORMAL_OK
    before, _SUBNORMAL_OK = _SUBNORMAL_OK, True
    try:
        yield
    finally:
        _SUBNORMAL_OK = before


def text_to_number(text: str, dates: bool = False) -> Decimal:
    """VALUE / implicit text-to-number conversion: spaces, commas, a currency sign, (5) and 5- are accepted. With ``dates`` (arithmetic,
    VALUE, CONVERT to DOUBLE) a text that is not a number is read as a date or a time, as DATEVALUE and TIMEVALUE read it (Task 19 Part E)."""
    cleaned = text.strip().replace(",", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned, negative = cleaned[1:-1].strip(), True
    if cleaned.startswith("$"):
        cleaned = cleaned[1:].strip()
    if cleaned.startswith(("-", "+")):
        sign = cleaned[0]
        rest = cleaned[1:].strip()
        if rest.startswith("$"):
            cleaned = sign + rest[1:].strip()
    if cleaned.endswith("-") and not cleaned.startswith(("-", "+")):
        cleaned, negative = cleaned[:-1].strip(), not negative
    if not _NUMBER_TEXT.match(cleaned):
        if dates:
            from . import dax_dates  # late import: dax_dates imports this module

            serial = dax_dates.text_serial(text)
            if serial is not None:
                return serial
            if dax_dates.date_shaped_text(text):  # a date shape no reader models ("1 1/2"): refused, never guessed
                raise refusal(f"The local engine does not model the text '{text.strip()}' as a number.")
        raise _error(f"Cannot convert value '{text}' of type Text to type Number.")
    as_double = float(cleaned)
    if math.isinf(as_double):  # Task 74 Part A: a text beyond the Double range is not a number (1e400 raises, measured)
        raise _error(f"Cannot convert value '{text}' of type Text to type Number.")
    number = Decimal(cleaned)
    if negative:
        number = -number
    if abs(as_double) < _TINY_TEXT and number != 0:
        # Task 74 Part A: the text is read as a Double. One that underflows to zero ("1e-400") is 0 (SIGN, NOT, LN and POWER see a zero, measured);
        # a tiny one (under 1E-300: the subnormals and the smallest normal double 2.2250738585072014E-308, measured) is refused: Power BI treats it as zero in some functions (SIGN, DIVIDE, POWER, MOD) and not in others (ABS, VALUE, LN), by
        # no rule found in four held-out grids.
        if as_double == 0:
            if number < 0:
                raise refusal(f"The local engine does not model the text '{text.strip()}' (a negative underflow is a negative zero).")
            return Decimal(0)
        if not _SUBNORMAL_OK:
            raise refusal(f"The local engine does not model the subnormal text conversion of '{text.strip()}'.")
        return Decimal(f"{as_double:.17g}")  # the double to 17 digits (it reads back exactly): LN("4.9e-324") is -744.440071921381, measured
    return number


_DOUBLE_EXACT_LIMIT = 2 ** 53


def beyond_double(text: str) -> bool:
    """Task 74 Part A: True when the text is a plain number (digits, a point, an exponent) beyond the Double range, such as 1e400."""
    spelled = text.strip(" ").replace(",", "")
    return bool(_BOOLEAN_NUMBER_TEXT.fullmatch(spelled)) and math.isinf(float(spelled))


def is_int64_form(number: Decimal) -> bool:
    """An exact whole number (exponent 0). The engine keeps a Double as a Decimal with an exponent, so those are not Int64s here."""
    return number.is_finite() and number == number.to_integral_value() and number.as_tuple().exponent == 0


def int64_through_double(number: Decimal) -> Decimal:
    """Task 74 Part B: an Int64 from 2^53 up is read as a Double by INT, TRUNC and ROUND (measured: INT, TRUNC and ROUND of 9223372036854775807
    are the conversion error, since its double is 2^63; so are INT and TRUNC of -9223372036854775807 and ROUND of the wrapped -2^63). A double of
    2^63 or more in size is the error. The literal -9223372036854775808 is a Double (not an exact whole Decimal): INT is the error there, ROUND
    and TRUNC are not, and that is left to the callers.
    """
    if not is_int64_form(number) or not (_DOUBLE_EXACT_LIMIT <= number < _INT64_LIMIT or -_INT64_LIMIT <= number <= -_DOUBLE_EXACT_LIMIT):
        return number
    as_double = Decimal(float(number))
    if abs(as_double) >= _INT64_LIMIT:
        raise _error("The result of a conversion or arithmetic operation is either too large or too small.")
    return as_double  # a negative one reads as its Double too (TRUNC(-(2^63-1024)) is -9.22337203685477E+18, measured)


def int64_fifteen_digits(number: Decimal) -> Decimal:
    """Task 74 Part B: FIXED reads an Int64 from 2^53 up through a double, shown to 15 significant digits (FIXED(9223372036854775807,0)
    is 9,223,372,036,854,780,000, measured)."""
    if not number.is_finite() or not _DOUBLE_EXACT_LIMIT <= abs(float(number)) <= _INT64_LIMIT:
        return number  # the literal -9223372036854775808 reads as the Double -2^63 (FIXED of it is -9,223,372,036,854,780,000.0, measured)
    return Decimal(f"{float(number):.15g}")


def to_number(value: object, dates: bool = False) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(1 if value else 0)
    if isinstance(value, str):
        return text_to_number(value, dates)
    return value  # type: ignore[return-value]


_BOOLEAN_NUMBER_TEXT = re.compile(r"[+-]?(?:[0-9][0-9,]*\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def to_boolean(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        # live Power BI (iteration 88, 34 texts x IF / NOT / AND): "" is FALSE, TRUE / FALSE in any case, and a number spelled in text is TRUE unless
        # it is zero; anything else (" TRUE", "T", "yes", "  ", "0x1", "TRUE()") is an error
        if value == "":
            return False
        folded = value.casefold()
        if folded in {"true", "false"}:
            return folded == "true"
        spelled = value.strip(" ")
        if spelled.startswith("$") and _BOOLEAN_NUMBER_TEXT.fullmatch(spelled[1:].lstrip(" ")):
            spelled = spelled[1:].lstrip(" ")  # Task 74 (t74c, measured): a currency sign is read, AND("$5","TRUE") is True and AND("$5","") BLANK
        elif spelled.startswith(("+", "-")):
            sign = spelled[0]
            rest = spelled[1:].lstrip(" ")
            if rest.startswith("$") and _BOOLEAN_NUMBER_TEXT.fullmatch(rest[1:].lstrip(" ")):
                spelled = sign + rest[1:].lstrip(" ")
        if _BOOLEAN_NUMBER_TEXT.fullmatch(spelled):
            if beyond_double(spelled):  # Task 74 Part A: a logical read of a text beyond the Double range (measured)
                raise _error("The following system error occurred: Out of present range.")
            return float(spelled.replace(",", "")) != 0  # a Double read: "1e-400" underflows to zero, so it is FALSE (Task 74, measured)
        raise _error(f"Cannot convert value '{value}' of type Text to type True/False.")
    return value != 0  # type: ignore[operator]


_ASTRAL = re.compile("[\U00010000-\U0010ffff]")
_WIDTH_FORMS = re.compile("[\uff00-\uffef]")
_WILDCARD_CHARS = re.compile(r"[*?~]")


def text_key(text: str) -> str:
    """Case-insensitive comparison key: Power BI folds code units up to U+FFFF only, and joins adjacent surrogate halves."""
    if text.isascii():
        return text.casefold()
    text = _from_units(text)
    if not _ASTRAL.search(text):
        return text.casefold()
    return "".join(c if ord(c) > 0xFFFF else c.casefold() for c in text)


_PUNCTUATION_ORDER = {character: rank for rank, character in enumerate(" !\"#$%&()*,./:;?@[\\]^_`{|}~+<=>")}
_IGNORED_AT_FIRST = {"'": 0, "\u02bc": 0, "-": 1}

_CULTURE_CHARS = re.compile("[\u0080-\ud7ff\ue000-\uffff]")


def _has_culture_chars(text: str) -> bool:
    """A non-ASCII character of the basic plane (surrogate halves and emoji are ordered by code unit and stay modelled)."""
    return not text.isascii() and _CULTURE_CHARS.search(text) is not None


_ACCENT_RANK = {
    0x301: 1,   # acute
    0x300: 2,   # grave
    0x307: 3,   # dot above
    0x302: 4,   # circumflex
    0x308: 5,   # diaeresis
    0x30C: 6,   # caron
    0x306: 7,   # breve
    0x304: 8,   # macron
    0x303: 9,   # tilde
    0x30A: 10,  # ring
    0x328: 11,  # ogonek
    0x327: 12,  # cedilla
    0x30B: 13,  # double acute
}

_SPECIAL_DIACRITIC = {
    "đ": 14, "Đ": 14, "ł": 14, "Ł": 14, "ø": 14, "Ø": 14, "ŀ": 15, "Ŀ": 15, "ð": 16, "Ð": 16,
}

_SPECIAL_EXPANSIONS = {
    "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss", "ẞ": "ss", "ĳ": "ij", "Ĳ": "ij",
    "ǆ": "dž", "Ǆ": "dž", "ǅ": "dž", "ǈ": "lj", "ǉ": "lj", "Ǉ": "lj", "ǌ": "nj", "ǋ": "nj", "Ǌ": "nj",
    "þ": "th", "Þ": "th", "ð": "d", "Ð": "d", "đ": "d", "Đ": "d", "ı": "i",
    "ŀ": "l", "Ŀ": "l", "ł": "l", "Ł": "l", "ŉ": "n", "ø": "o", "Ø": "o",
    "ſ": "ſ",
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st",
}


def is_classifiable_char(c: str) -> bool:
    if c.isascii():
        return c.isalnum() or c in _PUNCTUATION_ORDER or c in _IGNORED_AT_FIRST
    if c == "\u02bc":
        return True
    if c in _SPECIAL_EXPANSIONS:
        return True
    if ord(c) in _ACCENT_RANK:
        return True
    nfd = unicodedata.normalize("NFD", c)
    base = nfd[0]
    if not (base.isascii() and base.isalpha()):
        return False
    return all(ord(m) in _ACCENT_RANK for m in nfd[1:])


def is_classifiable_latin(text: str) -> bool:
    """Text made of ASCII letters, digits, punctuation, and Latin letters with diacritics / ligatures."""
    return all(is_classifiable_char(c) for c in text)


def decompose_char_stream(text: str) -> list[tuple[str, tuple[int, ...], int]]:
    text = _from_units(text)
    stream: list[tuple[str, tuple[int, ...], int]] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in _SPECIAL_EXPANSIONS:
            exp = _SPECIAL_EXPANSIONS[c]
            diac = _SPECIAL_DIACRITIC.get(c, 0)
            if c == "ſ":
                stream.append(("ſ", (), 0))
            elif diac > 0:
                stream.append((exp.lower(), (diac,), 0))
            elif c == "ı":
                stream.append(("i", (), 1))
            else:
                for sc in unicodedata.normalize("NFD", exp):
                    if unicodedata.category(sc) != "Mn":
                        stream.append((sc.lower(), (), 0))
                    else:
                        rnk = _ACCENT_RANK.get(ord(sc), 99)
                        base, d_tuple, v = stream[-1]
                        stream[-1] = (base, tuple(sorted(d_tuple + (rnk,))), v)
            i += 1
        else:
            nfd = unicodedata.normalize("NFD", c)
            for sc in nfd:
                if unicodedata.category(sc) == "Mn":
                    rnk = _ACCENT_RANK.get(ord(sc), 99)
                    if stream:
                        base, d_tuple, v = stream[-1]
                        stream[-1] = (base, tuple(sorted(d_tuple + (rnk,))), v)
                else:
                    stream.append((sc.lower(), (), 0))
            i += 1
    return stream


def _letter_rank(base: str) -> tuple[int, int]:
    if base == "ſ":
        return (ord("s"), 1)
    return (ord(base), 0)


def text_collation_key(text: str) -> tuple[tuple[tuple[int, tuple[int, int]], ...], tuple[tuple[int, ...], ...], tuple[int, ...], tuple[tuple[int, int], ...]]:
    stream = decompose_char_stream(text)
    primary: list[tuple[int, tuple[int, int]]] = []
    secondary: list[tuple[int, ...]] = []
    tertiary: list[int] = []
    quaternary: list[tuple[int, int]] = []
    for pos, (base, diacs, var) in enumerate(stream):
        if base in _IGNORED_AT_FIRST:
            quaternary.append((pos, _IGNORED_AT_FIRST[base]))
        elif base in _PUNCTUATION_ORDER:
            primary.append((0, (_PUNCTUATION_ORDER[base], 0)))
            secondary.append(diacs)
            tertiary.append(var)
        elif base.isdigit():
            primary.append((1, (ord(base), 0)))
            secondary.append(diacs)
            tertiary.append(var)
        elif base.isalpha() or base == "ſ":
            primary.append((2, _letter_rank(base)))
            secondary.append(diacs)
            tertiary.append(var)
        else:
            primary.append((3, (ord(base), 0)))
            secondary.append(diacs)
            tertiary.append(var)
    return (tuple(primary), tuple(secondary), tuple(tertiary), tuple(quaternary))


latin_collation_key = text_collation_key


def ordering_key(values: list[str]) -> Callable[[str], object]:
    """The key that orders these texts: the linguistic order of ASCII text (text_collation_key), or the one of Latin letters when a non-ASCII letter is there."""
    if not any(_has_culture_chars(value) for value in values):
        return text_collation_key
    if not all(is_classifiable_latin(value) for value in values):
        from .measures import MeasureError  # imported late: measures imports this module

        raise MeasureError("Ordering text with non-ASCII characters is not supported in the local engine.")
    return text_collation_key


def _strong_key(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().replace("æ", "ae").replace("œ", "oe")


def _stacked_marks(text: str) -> bool:
    """Two accents on one letter: Power BI ignores their order, which is not modelled."""
    previous_mark = False
    for c in unicodedata.normalize("NFD", text):
        is_mark = unicodedata.category(c) == "Mn"
        if is_mark and previous_mark:
            return True
        previous_mark = is_mark
    return False


def _is_pinned_post_latin_char(c: str) -> bool:
    o = ord(c)
    return (
        (0x0370 <= o <= 0x03FF) or (0x1F00 <= o <= 0x1FFF) or  # Greek & Greek Extended
        (0x0400 <= o <= 0x052F) or                              # Cyrillic & Cyrillic Supplement
        (0x0590 <= o <= 0x05FF) or                              # Hebrew
        (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or  # CJK Unified & Ext A
        (0x3040 <= o <= 0x30FF) or (0xF900 <= o <= 0xFAFF)     # Hiragana, Katakana & CJK Compat
    )


def _is_pinned_post_latin_text(text: str) -> bool:
    """Return True only if the text is entirely composed of pinned-script characters
    (Greek/Cyrillic/Hebrew/CJK) plus characters that are ignorable at the word level
    (apostrophe, modifier-apostrophe, hyphen from _IGNORED_AT_FIRST), AND the very first
    character is itself a pinned-script letter.

    Strings like " 東" (leading space) or "1α" (leading digit) do NOT qualify: the
    script rule is only safe when the FIRST character of the non-Latin text is itself
    a pinned-script letter. A leading space, digit or punctuation makes it refuse
    as before.
    """
    if not text:
        return False
    if not _is_pinned_post_latin_char(text[0]):
        return False
    for c in text:
        if _is_pinned_post_latin_char(c):
            continue
        elif c in _IGNORED_AT_FIRST:
            continue
        else:
            return False
    return True


def compare(operator: str, left: object, right: object, *, allow_variant: bool = False) -> bool:
    """DAX comparison: blank takes the other side's type, text ignores case, mixed types are an error."""
    if left is None and right is None:
        left, right = Decimal(0), Decimal(0)
    elif left is None:
        left = _blank_like(right)
    elif right is None:
        right = _blank_like(left)
    if isinstance(left, bool) != isinstance(right, bool) or isinstance(left, str) != isinstance(right, str):
        if allow_variant:
            # DAX Variant ordering at runtime: Blank < Number < Date < Text < Boolean
            def _variant_rank(v: object) -> int:
                if isinstance(v, bool):
                    return 3
                if isinstance(v, str):
                    return 2
                if isinstance(v, Decimal):
                    return 1
                return 0

            l_rank = _variant_rank(left)
            r_rank = _variant_rank(right)
            if l_rank != r_rank:
                if operator in {"=", "=="}:
                    return False
                if operator == "<>":
                    return True
                if operator == "<":
                    return l_rank < r_rank
                if operator == "<=":
                    return l_rank <= r_rank
                if operator == ">":
                    return l_rank > r_rank
                if operator == ">=":
                    return l_rank >= r_rank
        raise _error(
            "DAX comparison operations do not support comparing values of type "
            f"{type_name(left)} with values of type {type_name(right)}."
        )
    if isinstance(left, str):
        if _WIDTH_FORMS.search(left) or _WIDTH_FORMS.search(right):  # type: ignore[arg-type]
            # live Power BI (iteration 88): text comparison ignores the width of a character ("ａ" = "a" is True); that fold is not modelled
            from .measures import MeasureError  # imported late: measures imports this module

            raise MeasureError("Comparing text with full-width or half-width forms is not supported in the local engine.")
        has_culture = _has_culture_chars(left) or _has_culture_chars(right)  # type: ignore[arg-type]
        if has_culture:
            if not (is_classifiable_latin(left) and is_classifiable_latin(right)):  # type: ignore[arg-type]
                from .measures import MeasureError  # imported late: measures imports this module

                if is_classifiable_latin(left) and _is_pinned_post_latin_text(right):  # type: ignore[arg-type]
                    if operator in {"<", "<="}:
                        return True
                    if operator in {">", ">=", "=", "=="}:
                        return False
                    if operator == "<>":
                        return True
                if _is_pinned_post_latin_text(left) and is_classifiable_latin(right):  # type: ignore[arg-type]
                    if operator in {"<", "<=", "=", "=="}:
                        return False
                    if operator in {">", ">="}:
                        return True
                    if operator == "<>":
                        return True

                if operator in {"<", "<=", ">", ">="}:
                    raise MeasureError("Ordering text with non-ASCII characters is not supported in the local engine.")
                # identical texts are always equal; otherwise (as before the collation) texts that cannot be told apart by case fold alone are refused
                if left == right:
                    return operator in {"=", "==", "<=", ">="}
                fa, fb = text_key(left), text_key(right)  # type: ignore[arg-type]
                if (not is_classifiable_latin(left) and not is_classifiable_latin(right)) or (fa == fb) != (_strong_key(left) == _strong_key(right)) or any(c.casefold() != c.lower() for c in left + right) or _stacked_marks(left) or _stacked_marks(right):  # type: ignore[operator,arg-type]
                    raise MeasureError("Comparing text that differs only in composed, decomposed or expanded characters is not supported in the local engine.")
                a, b = fa, fb
            else:
                a, b = text_collation_key(left), text_collation_key(right)  # type: ignore[arg-type]
        else:
            a, b = (text_key(left), text_key(right)) if operator in {"=", "<>"} else (text_collation_key(left), text_collation_key(right))  # type: ignore[arg-type]
    elif isinstance(left, bool):
        a, b = int(left), int(right)  # type: ignore[arg-type]
    else:
        a, b = left, right
        if a.is_nan() or b.is_nan():  # type: ignore[union-attr]
            return operator == "<>"
    if operator in {"=", "=="}:
        return a == b
    if operator == "<>":
        return a != b
    if operator == "<":
        return a < b  # type: ignore[operator]
    if operator == "<=":
        return a <= b  # type: ignore[operator]
    if operator == ">":
        return a > b  # type: ignore[operator]
    if operator == ">=":
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
            if args[1] is not None:
                whole(args[1], function)  # Task 20 F4: a BLANK text still reads the count; an Infinity, a NaN or a text there is the error (a negative one is not)
            return None
        text = to_text(args[0])
        times = whole(args[1], function, minimum=0)
        if len(text) * times > 1 << 26:  # Power BI refuses a result beyond its text size limit
            raise _error("The result of function 'REPT' is longer than the allowed text size.")
        return text * times
    if function == "UNICHAR":
        if args[0] is None:
            return None  # Task 21 Part F: UNICHAR of a BLANK is BLANK
        code = whole(args[0], function, minimum=1)
        if code > 0x10FFFF or not _valid_unichar(code):
            raise _error("An argument of function 'UNICHAR' has the wrong data type or has an invalid value.")
        return chr(code)
    if function == "FIXED":
        return _fixed(args)
    if function in {"FIND", "SEARCH"}:
        from . import dax_misc  # late import: dax_misc imports this module
        if len(args) > 2 and args[2] is None:
            raise _error(f"An argument of function '{function}' has the wrong data type or the result is too large or too small.")
        if function == "SEARCH" and args[0] is None and args[1] is None:
            raise _error("The search Text provided to function 'SEARCH' could not be found in the given text.")
        return _find(function, args, "")
    first = args[0]
    if function == "VALUE":
        if first is None:
            return None
        if isinstance(first, Decimal):
            if not first.is_finite():  # live Power BI (Task 12 review): VALUE of Infinity or NaN cannot read the text it prints
                raise _error(f"Cannot convert value of type Number to type Number: {first} is not a number VALUE can read.")
            return Decimal(first)
        with subnormal_text_allowed():
            return text_to_number(to_text(first), dates=True)  # Task 19 Part E: VALUE reads a date or a time text too
    if first is None and function == "REPLACE":
        # Task 73 Part B: a BLANK text is "", so REPLACE returns the inserted text (REPLACE(BLANK(),2,1,"-1.5") is "-1.5")
        whole(args[1], function, minimum=1)
        whole(args[2], function, minimum=0)
        if args[3] is None:
            raise refusal("The local engine does not model REPLACE of a BLANK text with a BLANK new_text.")
        return _from_units(_units(to_text(args[3])))
    if first is None:
        if function in {"LEFT", "RIGHT"} and len(args) > 1 and args[1] is not None:
            whole(args[1], function, minimum=0)  # Task 20 F4: a BLANK text still reads the count (a negative one, an Infinity, a NaN or a text is the error)
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
        return _from_units(text[:count] if function == "LEFT" else (text[max(0, len(text) - count):] if count else ""))
    if function == "MID":
        start = whole(args[1], function, minimum=1)
        count = whole(args[2], function, minimum=0)
        return _from_units(text[start - 1:start - 1 + count])
    if function == "SUBSTITUTE":
        old, new = _units(to_text(args[1])), _units(to_text(args[2]))
        if not old:
            return _from_units(text)
        instance = whole(args[3], function, minimum=1) if len(args) > 3 and args[3] is not None else None
        from . import dax_misc  # late import: dax_misc imports this module
        pieces, last = [], 0
        for begin, finish in dax_misc.linguistic_spans(text, old, instance):  # Task 73: linguistic matching, case-sensitive
            pieces.extend((text[last:begin], new))
            last = finish
        replaced = "".join(pieces) + text[last:]
        if args[2] is None and not replaced:
            return None if text else ""  # Task 73 Part B: SUBSTITUTE of an empty text is "", never BLANK
        return _from_units(replaced)
    if function == "REPLACE":
        start = whole(args[1], function, minimum=1)
        count = whole(args[2], function, minimum=0)
        return _from_units(text[:start - 1] + _units(to_text(args[3])) + text[start - 1 + count:])
    if function in {"FIND", "SEARCH"}:
        return _find(function, args, text)
    raise _error(f"Function {function} is not supported by the local DAX engine.")


def _find(function: str, args: list[object], within_text: str) -> object:
    """FIND(find, within[, start[, notfound]]) and SEARCH (case-insensitive, ? * ~ wildcards), in UTF-16 code units."""
    from . import dax_misc  # late import: dax_misc imports this module
    needle = _units(to_text(args[0]))
    haystack = _units(to_text(args[1])) if len(args) > 1 else ""
    start = whole(args[2], function, minimum=1) if len(args) > 2 and args[2] is not None else 1
    not_found = _MISSING
    if len(args) > 3:  # the result is a number, so the NotFoundValue must convert to one; with one given nothing raises
        not_found = None if args[3] is None else Decimal(whole(args[3], function))
    if not needle:  # an empty needle is found at 1 provided the start lies inside the text (SEARCH refuses empty text)
        if start > max(len(haystack), 1) or (function == "SEARCH" and not haystack):
            found = -1
        else:
            return Decimal(1)
    elif start > len(haystack):
        found = -1
    elif function == "FIND" or not _WILDCARD_CHARS.search(needle):
        found = dax_misc.linguistic_position(haystack, needle, start - 1, ci=function == "SEARCH")  # Task 73: linguistic matching
    elif not (dax_misc.plain_text(needle) and dax_misc.plain_text(haystack)):
        raise refusal(f"The local engine does not model wildcards in {function} with accented or expanded text.")
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
        if decimals < 0:  # Task 74 Part C: FIXED of a NaN with negative decimals is the conversion error (FIXED(0/0,-1)); other cases are not measured
            if number.is_nan():
                raise _error("The result of a conversion or arithmetic operation is either too large or too small.")
            raise refusal("FIXED of an Infinity with negative decimals is not modelled by the local engine.")
        return number_to_text(number)
    if abs(number) >= Decimal(10) ** 60:
        # Task 74 (t74d): a Double this big shows its 15 significant digits and zeros (FIXED(1.7976931348623157E308,0) is 179,769,313,486,232,000...);
        # more decimals or fewer are not measured except the conversion error of -1 at the Double maximum, so they are refused
        if decimals != 0:
            raise refusal("FIXED of a number from 1E60 up with decimals other than 0 is not modelled by the local engine.")
        digits = Context(prec=15, rounding=ROUND_HALF_UP, traps=[]).plus(number)
        return f"{Decimal(digits).quantize(Decimal(1), context=Context(prec=400, traps=[])):{'' if no_commas else ','}.0f}"
    number = int64_fifteen_digits(number)
    quantum = Decimal(1).scaleb(-decimals)
    with_context = Context(prec=60, rounding=ROUND_HALF_UP, traps=[])
    rounded = with_context.quantize(number, quantum) if decimals >= 0 else (
        with_context.quantize(number, Decimal(1).scaleb(-decimals)).quantize(Decimal(1))
    )
    text = f"{rounded:{'' if no_commas else ','}.{max(decimals, 0)}f}"
    return text
