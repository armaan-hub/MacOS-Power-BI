"""Power Query ``Number.*`` functions, the numeric converters and the number constants (Task 103, m-number-93).

Result representation (measured live against Power BI, spec 2026-11-09-m-number-93-spec.json):

* Nearest rounding (``Number.Round``, ``Currency.From``, the integer converters) prints a TIE with the scale of
  its input: ``Number.Round(2.5)`` is ``2.0``, ``Number.Round(2.345, 2)`` is ``2.340``, ``Currency.From(1.00005)``
  is ``1.00000``. A result that is not a tie keeps ``min(digits, input scale)`` decimals: ``Round(2.345, 1)`` is
  ``2.3``, ``Round(2.5, 2)`` is ``2.5``. Zero is never negative.
* Decimal conversions (``Decimal.From``, ``Percentage.From``) keep the decimal digits of the input.
* ``Number.ToText`` and the ``.From`` text parsers follow en-US (and de-DE where measured). Any other culture or
  format that is not measured raises ``_unpinned``: an explicit ERR, never a guessed value.

Modes beyond the measured ones are documented at ``_nearest``. Every error message is copied from the spec.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import fractions as _fraction
import math
import random
import re
import struct
from typing import Callable, Optional

from . import values as V
from .canonical import number_text, number_text_of
from .values import MError, MValue

_CTX = _decimal.Context(prec=400, rounding=_decimal.ROUND_HALF_EVEN, Emax=10 ** 6, Emin=-10 ** 6)

INT64_MIN, INT64_MAX = -(2 ** 63), 2 ** 63 - 1
INT32_MIN, INT32_MAX = -(2 ** 31), 2 ** 31 - 1
DECIMAL_LIMIT = 2 ** 96
MAX_FACTORIAL = 170  # 171! overflows a double
MAX_PAIRS = 5000  # Combinations/Permutations above this are not computed (no measured answer)

NAN_ARGUMENT = "The argument value isn't valid."
NOT_NUMBER_TEXT = "We couldn't convert to Number."
NOT_LOGICAL_TEXT = "We couldn't convert to Logical."
INTEGER_EXPECTED = "We expected an integer value."
UNSIGNED = "This function operates only on Unsigned values, but value {} doesn't match the Unsigned pattern."

# RoundingMode values (not measured as numbers: only their behaviour on ties is modelled here)
ROUNDING_MODES = {"Up": 0.0, "Down": 1.0, "AwayFromZero": 2.0, "TowardZero": 3.0, "ToEven": 4.0}
_MODE_BY_CODE = {code: name for name, code in ROUNDING_MODES.items()}


# ---- helpers ------------------------------------------------------------------

def _native(params: tuple, fn: Callable[..., MValue]) -> V.Function:
    specs = tuple(V.ParamSpec(name, None, optional) for name, optional in params)

    def invoke(bound: list) -> MValue:
        return fn(*[V.force(item) for item in bound])

    return V.Function(specs, invoke)


def _unpinned(what: str) -> MError:
    """Not a Power BI answer we have measured: an explicit ERR, never a guessed value."""
    return V.generic_error(f"The {what} is not supported by this engine yet.")


def _range(bits: str) -> MError:
    return MError("Expression.Error", f"The number is out of range of {bits}.")


def _result(value: float, text: Optional[str] = None) -> V.Number:
    """A Number whose printed text is ``text`` (a Decimal result) when that differs from the double's text."""
    if text is None or text == number_text(value):
        return V.Number(value)
    return V.Number(value, exact=text)


def _is_special(x: float) -> bool:
    return math.isnan(x) or math.isinf(x)


def _symbol(x: float) -> str:
    """The value text used inside messages: -#infinity, -2.5, -1E-06 (exact literal text when it has one)."""
    if math.isinf(x):
        return "-#infinity" if x < 0 else "#infinity"
    return number_text(x)


def _num(value: MValue) -> float:
    """A Number argument of an ordinary function (text, logical and the rest are convert errors)."""
    if isinstance(value, V.Number):
        return value.value
    raise V.convert_error(value, V.TypeValue("number"))


def _text_arg(value: MValue) -> str:
    if isinstance(value, V.Text):
        return value.value
    raise V.convert_error(value, V.TypeValue("text"))


def _decimal_of(number: V.Number) -> _decimal.Decimal:
    """The decimal digits of a Number: the literal text when it keeps one, else the double's 15 significant digits."""
    if number.exact is not None:
        return _decimal.Decimal(number.exact)
    return _decimal.Decimal(format(number.value, ".15g"))


def _scale(d: _decimal.Decimal) -> int:
    return max(0, -d.as_tuple().exponent)


def _decimal_result(q: _decimal.Decimal) -> V.Number:
    if q == 0:
        q = abs(q)  # never a negative zero
    return _result(float(q), format(q, "f"))


def _nearest(scaled: _decimal.Decimal, mode: str) -> tuple:
    """Nearest integer of ``scaled`` (a Decimal), ties by ``mode``; returns (integer, is_tie).

    ToEven: banker's rounding. AwayFromZero: ties away from zero. TowardZero: ties toward zero.
    Up / Down: ties toward +infinity / -infinity (the names' only measured meaning is the non-tie nearest answer)."""
    floor = scaled.to_integral_value(rounding=_decimal.ROUND_FLOOR, context=_CTX)
    frac = scaled - floor
    half = _decimal.Decimal("0.5")
    if frac < half:
        return floor, False
    if frac > half:
        return floor + 1, False
    up = floor + 1
    if mode == "ToEven":
        return (floor if int(floor) % 2 == 0 else up), True
    if mode == "AwayFromZero":
        return (up if scaled > 0 else floor), True
    if mode == "TowardZero":
        return (floor if scaled > 0 else up), True
    if mode == "Up":
        return up, True
    if mode == "Down":
        return floor, True
    raise _unpinned("rounding mode")


def _round_nearest(number: V.Number, digits: int, mode: str) -> V.Number:
    """Nearest rounding to ``digits`` places with the measured scale rule (module docstring)."""
    with _decimal.localcontext(_CTX):
        d = _decimal_of(number)
        scale_in = _scale(d)
        scaled = d.scaleb(digits, context=_CTX)
        integer, tie = _nearest(scaled, mode)
        target = scale_in if tie else (min(digits, scale_in) if digits > 0 and integer != 0 else 0)
        q = integer.scaleb(-digits, context=_CTX).quantize(_decimal.Decimal(1).scaleb(-target), context=_CTX)
        return _decimal_result(q)


def _round_directed(number: V.Number, digits: int, rounding: str) -> V.Number:
    with _decimal.localcontext(_CTX):
        d = _decimal_of(number)
        scale_in = _scale(d)
        integer = d.scaleb(digits, context=_CTX).to_integral_value(rounding=rounding, context=_CTX)
        target = min(digits, scale_in) if digits > 0 and integer != 0 else 0
        q = integer.scaleb(-digits, context=_CTX).quantize(_decimal.Decimal(1).scaleb(-target), context=_CTX)
        return _decimal_result(q)


def _digits_arg(value: MValue) -> int:
    x = _num(value)
    if _is_special(x) or x != math.floor(x) or abs(x) > 100:
        raise _unpinned("digits argument")
    return int(x)


def _mode_arg(value: MValue) -> str:
    if isinstance(value, V.Null):
        return "ToEven"
    x = _num(value)
    if x not in _MODE_BY_CODE:
        raise _unpinned("rounding mode value")
    return _MODE_BY_CODE[x]


# ---- Number.Round family ------------------------------------------------------

def _round(number: MValue, digits: MValue = V.Null(), mode: MValue = V.Null()) -> MValue:
    """An omitted digits argument arrives as null (the evaluator binds it so): null means 0 places."""
    if isinstance(number, V.Null):
        return V.Null()
    x = _num(number)
    if _is_special(x):
        return V.Number(x)
    places = 0 if isinstance(digits, V.Null) else _digits_arg(digits)
    return _round_nearest(number, places, _mode_arg(mode))


def _directed(rounding: str) -> Callable[..., MValue]:
    def fn(number: MValue, digits: MValue = V.Null()) -> MValue:
        if isinstance(number, V.Null):
            return V.Null()
        x = _num(number)
        if _is_special(x):
            return V.Number(x)
        places = 0 if isinstance(digits, V.Null) else _digits_arg(digits)
        return _round_directed(number, places, rounding)

    return fn


# ---- arithmetic and trigonometry ---------------------------------------------

def _unary(fn: Callable[[float], float]) -> Callable[[MValue], MValue]:
    def invoke(value: MValue) -> MValue:
        if isinstance(value, V.Null):
            return V.Null()
        return V.Number(fn(_num(value)))

    return invoke


def _refusing(name: str, fn: Callable[[float], Optional[float]]) -> Callable[[MValue], MValue]:
    """A one-argument function that returns a value only when ``fn`` can prove it (None means refuse)."""
    def invoke(value: MValue) -> MValue:
        if isinstance(value, V.Null):
            return V.Null()
        result = fn(_num(value))
        if result is None:
            raise _refusal(name)
        return V.Number(result)

    return invoke


def _binary(fn: Callable[[float, float], float]) -> Callable[..., MValue]:
    def invoke(first: MValue, second: MValue) -> MValue:
        if isinstance(first, V.Null) or isinstance(second, V.Null):
            return V.Null()
        return V.Number(fn(_num(first), _num(second)))

    return invoke


def _sign(x: float) -> float:
    if math.isnan(x):
        raise MError("Expression.Error", NAN_ARGUMENT)
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def _sqrt(x: float) -> float:
    if math.isnan(x) or x < 0:
        return math.nan
    return math.sqrt(x)


def _exp(x: float) -> float:
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def _ln(x: float) -> float:
    if math.isnan(x):
        return math.nan
    if x == 0:
        return -math.inf
    if x < 0:
        return math.nan
    return math.log(x) if not math.isinf(x) else math.inf


def _log10(x: float) -> float:
    if math.isnan(x):
        return math.nan
    if x == 0:
        return -math.inf
    if x < 0:
        return math.nan
    return math.log10(x) if not math.isinf(x) else math.inf


# Power BI's own sin, cos, tan, asin, acos, atan, atan2, sinh, cosh, tanh, pow and log-with-a-base results differ from
# the correctly rounded value by one unit in the last place for roughly 1 input in 4 to 1 in 20, and the rule is not
# known. These functions therefore return a value only when it is provably what Power BI returns (measured special
# ranges, results that are exact by mathematics, NaN / infinity cases); every other input is an explicit refusal.
# Each function below returns None for "refuse".

def _refusal(name: str) -> MError:
    return MError("Expression.Error", f"The result of {name} for this input cannot be reproduced exactly by the local engine.")


def _log(x: float, base: float) -> Optional[float]:
    if math.isnan(x) or math.isnan(base) or x < 0 or base < 0 or base == 0:
        return math.nan  # measured: a zero or negative base, a negative number: NaN
    if x == 1.0 and not math.isinf(base) and base != 1.0:
        return 0.0
    if x == base and not math.isinf(x) and x != 1.0:
        return 1.0
    return None


# Measured: Power BI's sine, cosine and tangent are 0 for 2**30 < |x| < 2**63; from 2**63 on sine and cosine give the
# argument back, and the tangent leaves whatever the floating-point stack held (0, -Infinity, an earlier argument).
# Below 2**30 the value is only provable at 0.
_TRIG_LIMIT = 2.0 ** 30
_TRIG_RANGE = 2.0 ** 63


def _trig(at_zero: float, echo: bool) -> Callable[[float], Optional[float]]:
    def invoke(x: float) -> Optional[float]:
        if _is_special(x):
            return math.nan
        if x == 0:
            return x if at_zero == 0 else at_zero
        if abs(x) <= _TRIG_LIMIT:
            return None
        if abs(x) < _TRIG_RANGE:
            return 0.0
        return x if echo else None

    return invoke


_sin = _trig(0.0, True)
_cos = _trig(1.0, True)
_tan = _trig(0.0, False)


def _asin(x: float) -> Optional[float]:
    if math.isnan(x) or abs(x) > 1:
        return math.nan
    return x if x == 0 else None


def _acos(x: float) -> Optional[float]:
    if math.isnan(x) or abs(x) > 1:
        return math.nan
    return 0.0 if x == 1 else None


def _atan(x: float) -> Optional[float]:
    if math.isnan(x):
        return math.nan
    if math.isinf(x):
        return math.atan(x)  # +-pi/2 (measured 1.5707963267948966)
    return x if x == 0 else None


_HYPERBOLIC_OVERFLOW = 720.0  # sinh and cosh exceed the largest double well before this
_TANH_ONE = 40.0  # tanh is 1 to the last digit from here on


def _sinh(x: float) -> Optional[float]:
    if math.isnan(x):
        return math.nan
    if x == 0 or abs(x) > _HYPERBOLIC_OVERFLOW:
        return x if x == 0 else math.copysign(math.inf, x)
    return None


def _cosh(x: float) -> Optional[float]:
    if math.isnan(x):
        return math.nan
    if x == 0:
        return 1.0
    return math.inf if abs(x) > _HYPERBOLIC_OVERFLOW else None


def _tanh(x: float) -> Optional[float]:
    if math.isnan(x):
        return math.nan
    if x == 0:
        return x
    return math.copysign(1.0, x) if abs(x) >= _TANH_ONE else None


_MIN_NORMAL = 2.0 ** -1022


def _power(x: float, y: float) -> Optional[float]:
    if x == 0 and y == 0:
        return math.nan  # measured: Number.Power(0, 0) is NaN
    if math.isnan(x):
        return math.nan  # measured: Power(NaN, 0) is NaN
    if math.isnan(y):
        return None if x == 1.0 else math.nan
    if math.isinf(x) or math.isinf(y):
        if abs(x) == 1.0:
            return None
        try:
            return math.pow(x, y)
        except (OverflowError, ValueError):
            return None
    if x == 0:
        return math.inf if y < 0 else 0.0  # measured: Power(0, -1) is Infinity
    if y == 0 or x == 1.0:
        return 1.0
    if y == 1.0:
        return x
    if y != math.floor(y) or abs(y) > 2000:
        return None
    n = int(y)
    reach = abs(n) * abs(math.log2(abs(x)))
    if reach > 1100:
        if n > 0 and abs(x) > 1:
            return -math.inf if (x < 0 and n % 2) else math.inf
        return None
    exact = _fraction.Fraction(x) ** n
    if exact != 0 and abs(exact) < _MIN_NORMAL:
        return None  # measured: Power BI gives 0 for 2**-1074; not modelled
    try:
        result = float(exact)
    except OverflowError:
        return -math.inf if exact < 0 and abs(exact) >= 2 ** 1024 else (math.inf if exact >= 2 ** 1024 else None)
    return result if _fraction.Fraction(result) == exact else None


def _atan2(y: float, x: float) -> Optional[float]:
    if math.isnan(y) or math.isnan(x):
        return math.nan
    return y if (y == 0 and x >= 0) else None  # measured: Atan2(0, 0) is 0


def _mod(x: float, y: float) -> float:
    try:
        return math.fmod(x, y)
    except ValueError:
        return math.nan


def _integer_divide(x: float, y: float) -> float:
    if y == 0:
        return math.nan
    q = x / y
    if _is_special(q):
        return q if not math.isnan(q) else math.nan
    return float(math.trunc(q))




def _is_even(value: MValue) -> MValue:
    x = _num(value)
    if _is_special(x):
        return V.Logical(False)
    return V.Logical(math.floor(x) % 2 == 0)


def _is_odd(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        raise V.convert_error(value, V.TypeValue("number"))
    x = _num(value)
    if _is_special(x):
        return V.Logical(False)
    return V.Logical(math.floor(x) % 2 == 1)


def _is_nan(value: MValue) -> MValue:
    return V.Logical(math.isnan(_num(value)))


def _abs(value: MValue) -> MValue:
    """A Decimal-typed value keeps its digits (measured: ``Number.Abs(123456789.987654321)``)."""
    if isinstance(value, V.Null):
        return V.Null()
    x = _num(value)
    if value.exact is not None:
        return V.Number(abs(x), exact=value.exact.lstrip("-"))
    return V.Number(abs(x))


def _sign_of(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    return V.Number(_sign(_num(value)))


def _ln_of(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    return V.Number(_ln(_num(value)))


def _log10_of(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    return V.Number(_log10(_num(value)))


def _log_of(number: MValue, base: MValue = V.Null()) -> MValue:
    if isinstance(number, V.Null):
        return V.Null()
    x = _num(number)
    if isinstance(base, V.Null):
        return V.Number(_ln(x))  # measured: a null base means e
    result = _log(x, _num(base))
    if result is None:
        raise _refusal("Number.Log")
    return V.Number(result)


def _power_of(number: MValue, power: MValue) -> MValue:
    if isinstance(number, V.Null) or isinstance(power, V.Null):
        return V.Null()
    result = _power(_num(number), _num(power))
    if result is None:
        raise _refusal("Number.Power")
    return V.Number(result)


def _mod_of(number: MValue, divisor: MValue) -> MValue:
    if isinstance(number, V.Null) or isinstance(divisor, V.Null):
        return V.Null()
    return V.Number(_mod(_num(number), _num(divisor)))


def _integer_divide_of(number: MValue, divisor: MValue) -> MValue:
    if isinstance(number, V.Null) or isinstance(divisor, V.Null):
        return V.Null()
    return V.Number(_integer_divide(_num(number), _num(divisor)))


def _atan2_of(y: MValue, x: MValue) -> MValue:
    if isinstance(y, V.Null) or isinstance(x, V.Null):
        return V.Null()
    result = _atan2(_num(y), _num(x))
    if result is None:
        raise _refusal("Number.Atan2")
    return V.Number(result)


def _random() -> MValue:
    return V.Number(random.random())


def _random_between(low: MValue, high: MValue) -> MValue:
    if isinstance(low, V.Null) or isinstance(high, V.Null):
        return V.Null()
    a, b = _num(low), _num(high)
    return V.Number(random.uniform(a, b) if a != b else a)


# ---- integers: strict conversions (bitwise, factorial, combinatorics) ----------

def _strict_int(x: float, bits: str = "a 64 bit integer value", lo: int = INT64_MIN, hi: int = INT64_MAX) -> int:
    """An integer argument: not rounded; a fraction, NaN, infinity or an out-of-range value is an error."""
    if _is_special(x) or x != math.floor(x) or not lo <= int(x) <= hi:
        raise _range(bits)
    return int(x)


def _unsigned(x: float) -> None:
    if x < 0:
        raise MError("Expression.Error", UNSIGNED.format(_symbol(x)))


def _wrap64(v: int) -> int:
    return ((v + 2 ** 63) % 2 ** 64) - 2 ** 63


def _bitwise(op: Callable[[int, int], int]) -> Callable[..., MValue]:
    def invoke(first: MValue, second: MValue) -> MValue:
        if isinstance(first, V.Null) or isinstance(second, V.Null):
            return V.Null()
        a = _strict_int(_num(first))
        b = _strict_int(_num(second))
        return V.Number(float(_wrap64(op(a, b))))

    return invoke


def _bitwise_not(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    return V.Number(float(_wrap64(~_strict_int(_num(value)))))


def _shift(left: bool) -> Callable[..., MValue]:
    def invoke(value: MValue, count: MValue) -> MValue:
        if isinstance(value, V.Null) or isinstance(count, V.Null):
            return V.Null()
        a = _strict_int(_num(value))
        n = _strict_int(_num(count), "a 32 bit integer value", INT32_MIN, INT32_MAX)
        if not 0 <= n <= 63:
            raise _unpinned("shift count outside 0 to 63")
        return V.Number(float(_wrap64(a << n if left else a >> n)))

    return invoke


def _factorial(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    x = _num(value)
    _unsigned(x)
    n = _strict_int(x)
    if n > MAX_FACTORIAL:
        return V.Number(math.inf)
    product = 1.0  # measured: Power BI multiplies from n down to 2 in double precision (Factorial(170))
    for factor in range(n, 1, -1):
        product *= factor
    return V.Number(product)


def _pair(n: MValue, k: MValue) -> tuple:
    a = _num(n)
    _unsigned(a)
    b = _num(k)
    _unsigned(b)
    return _strict_int(a), _strict_int(b)


def _combinations(n: MValue, k: MValue) -> MValue:
    if isinstance(n, V.Null) or isinstance(k, V.Null):
        return V.Null()
    a, b = _pair(n, k)
    if b > a:
        return V.Number(0.0)
    if min(b, a - b) > MAX_PAIRS:
        raise _unpinned("combination of this size")
    return V.Number(float(math.comb(a, b)))


def _permutations(n: MValue, k: MValue) -> MValue:
    if isinstance(n, V.Null) or isinstance(k, V.Null):
        return V.Null()
    a, b = _pair(n, k)
    if b > a:
        return V.Number(0.0)
    if b > MAX_PAIRS:
        raise _unpinned("permutation of this size")
    return V.Number(float(math.perm(a, b)))


# ---- conversions --------------------------------------------------------------

_EPOCH_TICKS = V.date_ticks(_dt.date(1899, 12, 30))
_EN, _DE = "en-US", "de-DE"
_SYMBOLS = {_EN: (",", ".", "$"), _DE: (".", ",", "€")}  # group separator, decimal separator, currency symbol


def _culture(value: MValue) -> str:
    """The culture argument: null means en-US; only en-US and de-DE are measured."""
    if isinstance(value, V.Null):
        return _EN
    name = _text_arg(value).lower()
    if name in ("en-us", "en"):
        return _EN
    if name in ("de-de", "de"):
        return _DE
    raise _unpinned("culture")


def _scan(s: str, culture: str, spaced: bool) -> Optional[tuple]:
    """The .NET "Any" number scan: (negative, plain number text) or None.

    Leading: white space (not after a sign unless ``spaced``), one sign or an opening parenthesis, one currency
    symbol, in any order. Then digits with group separators, one decimal separator, an exponent. Trailing: white
    space, one sign (only when no leading sign), the closing parenthesis, one currency symbol."""
    group, decimal_sep, currency = _SYMBOLS[culture]
    n = len(s)
    i = 0
    signed = paren = cur_seen = negative = False
    while i < n:
        ch = s[i]
        if ch.isspace() and (not signed or (spaced and not paren)):
            i += 1
        elif ch in "+-" and not signed:
            signed, negative = True, ch == "-"
            i += 1
        elif ch == "(" and not signed:
            signed = paren = negative = True
            i += 1
        elif not cur_seen and s.startswith(currency, i):
            cur_seen = True
            i += len(currency)
        else:
            break
    digits = []
    seen_decimal = False
    count = 0
    while i < n:
        ch = s[i]
        if "0" <= ch <= "9":
            digits.append(ch)
            count += 1
        elif ch == decimal_sep and not seen_decimal:
            seen_decimal = True
            digits.append(".")
        elif ch == group and count > 0 and not seen_decimal:
            pass
        else:
            break
        i += 1
    if count == 0:
        return None
    exponent = ""
    if i < n and s[i] in "eE":
        k = i + 1
        sign = ""
        if k < n and s[k] in "+-":
            sign = s[k]
            k += 1
        start = k
        while k < n and "0" <= s[k] <= "9":
            k += 1
        if k > start:
            exponent = "e" + sign + s[start:k]
            i = k
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
        elif ch in "+-" and not signed:
            signed, negative = True, ch == "-"
            i += 1
        elif ch == ")" and paren:
            paren = False
            i += 1
        elif not cur_seen and s.startswith(currency, i):
            cur_seen = True
            i += len(currency)
        else:
            break
    if i != n or paren:
        return None
    return negative, "".join(digits) + exponent


def _parse_text(text: str, culture: str) -> Optional[V.Number]:
    """The Number a numeric text denotes (en-US / de-DE), or None when the text is not a number.

    A number the .NET Decimal holds keeps its exact digits like a literal (``Number.FromText`` of 17 digits).
    A percent sign (one, before or after the number, or ``-%n`` / ``n%-``) divides by 100 as a Decimal."""
    s = text.strip()
    percent = False
    extra_negative = False
    if s.endswith("%"):
        s, percent = s[:-1], True
    elif s.startswith("%"):
        s, percent = s[1:], True
    elif s.startswith("-%"):
        s, percent, extra_negative = s[2:], True, True
    elif s.endswith("%-"):
        s, percent, extra_negative = s[:-2], True, True
    s = s.strip() if percent else s
    special = {"NaN": math.nan, "∞": math.inf, "-∞": -math.inf}.get(s)
    if special is not None:
        if percent:
            raise _range("a decimal value")
        return V.Number(special)
    scanned = _scan(s, culture, percent)
    if scanned is None:
        return None
    negative, body = scanned
    if extra_negative:
        if negative:
            return None
        negative = True
    number = V.number_from_literal(("-" if negative else "") + body)
    if not percent:
        return number
    with _decimal.localcontext(_CTX):
        d = _decimal_of(number)
        if abs(d) >= DECIMAL_LIMIT:
            raise _range("a decimal value")
        q = d.scaleb(-2, context=_CTX)
        if _scale(q) > 28:
            q = q.quantize(_decimal.Decimal(1).scaleb(-28), rounding=_decimal.ROUND_HALF_EVEN, context=_CTX)
        q = q.normalize(context=_CTX)  # a Decimal division drops trailing zeros: 50% is 0.5
        if q.as_tuple().exponent > 0:
            q = q.quantize(_decimal.Decimal(1), context=_CTX)
        return _decimal_result(q)


def _text_number(text: str, culture: str) -> V.Number:
    number = _parse_text(text, culture)
    if number is None:
        raise MError("DataFormat.Error", NOT_NUMBER_TEXT)
    return number


def _as_typed(value: MValue, culture: str = _EN) -> Optional[V.Number]:
    """A conversion source as a Number: numbers as they are (a Decimal keeps its digits), logicals (1 / 0), texts
    parsed, the date/time values as serials. None for the empty text."""
    if isinstance(value, V.Number):
        return value
    if isinstance(value, V.Logical):
        return V.Number(1.0 if value.value else 0.0)
    if isinstance(value, V.Text):
        if value.value == "":
            return None
        return _text_number(value.value, culture)
    if isinstance(value, V.Date):
        return V.Number(float((V.date_ticks(value.value) - _EPOCH_TICKS) // V.TICKS_PER_DAY))
    if isinstance(value, V.DateTime):
        days, rest = divmod(value.ticks - _EPOCH_TICKS, V.TICKS_PER_DAY)
        return V.Number(days + rest / V.TICKS_PER_DAY)
    if isinstance(value, V.Time):
        return V.Number(value.ticks / V.TICKS_PER_DAY)
    if isinstance(value, V.Duration):
        return V.Number(value.ticks / V.TICKS_PER_DAY)
    raise MError("DataFormat.Error", NOT_NUMBER_TEXT)


def _number_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Number):
        return value
    number = _as_typed(value, _culture(culture))
    return V.Null() if number is None else number


def _number_from_text(text: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(text, V.Null):
        return V.Null()
    raw = _text_arg(text)
    if raw == "":
        return V.Null()
    return _text_number(raw, _culture(culture))


def _integer_from(bits: str, lo: int, hi: int, small: bool) -> Callable[..., MValue]:
    """Int8/Int16/Byte/Int32/Int64 .From: round (ToEven unless a mode is given) then range check.

    Measured messages: a NaN or infinity is the 64-bit message for Int8, Int16, Byte and Int64 and the 32-bit
    message for Int32. The result of Int64.From keeps all its digits (``Int64.From(9223372036854775807)``)."""
    def invoke(value: MValue, culture: MValue = V.Null(), mode: MValue = V.Null()) -> MValue:
        if isinstance(value, V.Null):
            return V.Null()
        source = _as_typed(value, _culture(culture))
        if source is None:
            return V.Null()
        rounding = _mode_arg(mode)
        if _is_special(source.value):
            raise _range("a 64 bit integer value" if small else bits)
        with _decimal.localcontext(_CTX):
            integer, _ = _nearest(_decimal_of(source), rounding)
            integer = int(integer)
        if not lo <= integer <= hi:
            raise _range(bits)
        return _result(float(integer), str(integer))

    return invoke


def _int_bits(name: str) -> tuple:
    return {"Int8": ("an 8 bit integer value", -128, 127, True),
            "Int16": ("a 16 bit integer value", -32768, 32767, True),
            "Byte": ("a byte value", 0, 255, True),
            "Int32": ("a 32 bit integer value", INT32_MIN, INT32_MAX, False),
            "Int64": ("a 64 bit integer value", INT64_MIN, INT64_MAX, False)}[name]


def _decimal_from(value: MValue, culture: MValue = V.Null(), percent: bool = False) -> MValue:
    """Decimal.From / Percentage.From: the value's decimal digits, 28 places at most."""
    if isinstance(value, V.Null):
        return V.Null()
    source = _as_typed(value, _culture(culture))
    if source is None:
        return V.Null()
    if _is_special(source.value):
        raise _range("a decimal value")
    with _decimal.localcontext(_CTX):
        d = _decimal_of(source)
        if abs(d) >= DECIMAL_LIMIT:
            raise _range("a decimal value")
        if _scale(d) > 28:
            d = d.quantize(_decimal.Decimal(1).scaleb(-28), rounding=_decimal.ROUND_HALF_EVEN, context=_CTX)
        return _decimal_result(d)


def _currency_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    """Currency.From: decimal digits rounded to 4 places (ToEven, measured tie rule)."""
    if isinstance(value, V.Null):
        return V.Null()
    number = _as_typed(value, _culture(culture))
    if number is None:
        return V.Null()
    if _is_special(number.value):
        raise _range("a decimal value")
    if abs(number.value) >= 2.0 ** 96:
        raise _range("a decimal value")
    return _round_nearest(number, 4, "ToEven")


def _double_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    number = _as_typed(value, _culture(culture))
    return V.Null() if number is None else V.Number(number.value)


def _single_from(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    number = _as_typed(value, _culture(culture))
    if number is None:
        return V.Null()
    x = number.value
    if _is_special(x):
        return V.Number(x)
    try:
        return V.Number(struct.unpack("<f", struct.pack("<f", x))[0])
    except OverflowError:
        raise _unpinned("single-precision value out of range")


def _logical_from(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Logical):
        return value
    if isinstance(value, V.Number):
        return V.Logical(value.value != 0.0)  # NaN is true (measured)
    if isinstance(value, V.Text):
        return _logical_from_text(value)
    raise V.convert_error(value, V.TypeValue("logical"))


def _logical_from_text(value: MValue, culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    text = _text_arg(value).strip().lower()
    if text == "true":
        return V.Logical(True)
    if text == "false":
        return V.Logical(False)
    raise MError("Expression.Error", NOT_LOGICAL_TEXT)


def _logical_to_text(value: MValue) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    if isinstance(value, V.Logical):
        return V.Text("true" if value.value else "false")
    raise V.convert_error(value, V.TypeValue("logical"))


# ---- Number.ToText ------------------------------------------------------------
#
# Measured: a double formats from its 15 significant digits (17 when the format asks for more: E16, G17), a value
# with a Decimal representation (a literal with more than 15 digits, Int64.From, Decimal.From) from its exact
# digits. Ties round away from zero. A negative value that rounds to zero has no sign. An integral double of
# 1e15 .. 2**96 ignores the format and prints as Number.ToText(x) does.

_STANDARD = re.compile(r"([CDEFGNPRXcdefgnprx])([0-9]*)")
_CUSTOM_SECTION = re.compile(r"([^#0,.]*)([#0,.]+)([^#0,.]*)")
_LITERALS = frozenset("()$€% -+")
_HALF_UP = _decimal.ROUND_HALF_UP


def _group(digits: str, sep: str) -> str:
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return sep.join(out)


def _digits_of(number: V.Number, wanted: int) -> _decimal.Decimal:
    """The decimal digits a format starts from: the exact digits of a Decimal-typed Number, else the double's 15
    significant digits (``wanted`` <= 15) or ``wanted`` of them up to 17."""
    if number.exact is not None:
        return _decimal.Decimal(number.exact)
    count = 15 if wanted <= 15 else min(wanted, 17)
    return _decimal.Decimal(format(number.value, f".{count - 1}e"))


def _round_places(d: _decimal.Decimal, places: int) -> _decimal.Decimal:
    return d.quantize(_decimal.Decimal(1).scaleb(-places), rounding=_HALF_UP, context=_CTX)


def _round_sig(d: _decimal.Decimal, count: int) -> _decimal.Decimal:
    if d == 0:
        return d
    return _round_places(d, count - 1 - d.adjusted())


def _fixed_parts(number: V.Number, prec: int, scale: int = 0) -> tuple:
    """(integer digits, fraction digits, negative) of the value (times 10**scale) rounded to ``prec`` places."""
    with _decimal.localcontext(_CTX):
        d = _digits_of(number, 15)
        if scale:
            d = d.scaleb(scale, context=_CTX)
        q = _round_places(d, prec)
        whole, _, frac = format(abs(q), "f").partition(".")
    return whole, frac, q < 0


def _scientific(number: V.Number, prec: int, lower: bool) -> str:
    with _decimal.localcontext(_CTX):
        d = _digits_of(number, prec + 1)
        if d == 0:
            e = 0
            m = _decimal.Decimal(0).quantize(_decimal.Decimal(1).scaleb(-prec), context=_CTX)
        else:
            r = _round_sig(d, prec + 1)
            e = r.adjusted()
            m = abs(r).scaleb(-e, context=_CTX).quantize(_decimal.Decimal(1).scaleb(-prec), context=_CTX)
    sign = "-" if d < 0 else ""
    return f"{sign}{format(m, 'f')}{'e' if lower else 'E'}{'+' if e >= 0 else '-'}{abs(e):03d}"


def _general(number: V.Number, prec: int, lower: bool) -> str:
    """The "G" format: ``prec`` significant digits (0 / absent: 15 for a double, all digits for a Decimal)."""
    if prec == 0 and number.exact is not None:
        return number.exact
    count = prec or 15
    with _decimal.localcontext(_CTX):
        d = _digits_of(number, count)
        if d == 0:
            return "0"
        r = _round_sig(d, count)
        e = r.adjusted()
        coefficient = "".join(str(c) for c in r.as_tuple().digits).rstrip("0") or "0"
        sign = "-" if d < 0 else ""
        if e >= count or e < -4:
            mantissa = coefficient[0] + ("." + coefficient[1:] if len(coefficient) > 1 else "")
            return f"{sign}{mantissa}{'e' if lower else 'E'}{'+' if e >= 0 else '-'}{abs(e):02d}"
        return sign + format(abs(r).normalize(), "f")


def _integer_of(number: V.Number) -> int:
    """The integer a D / X format needs: an integral value inside the signed 64-bit range (checked on the double)."""
    x = number.value
    if _is_special(x) or not -(2.0 ** 63) <= x < 2.0 ** 63:
        raise MError("Expression.Error", INTEGER_EXPECTED)
    if number.exact is not None:
        d = _decimal.Decimal(number.exact)
        if d != d.to_integral_value():
            raise MError("Expression.Error", INTEGER_EXPECTED)
        return int(d)
    if x != math.floor(x):
        raise MError("Expression.Error", INTEGER_EXPECTED)
    return int(x)


def _custom(number: V.Number, fmt: str, culture: str) -> str:
    x = number.value
    if x != 0 and x == math.floor(x) and 1e15 <= abs(x) < 2.0 ** 96 and number.exact is None:
        return number_text(x).replace(".", _SYMBOLS[culture][1])
    sections = fmt.split(";")
    if len(sections) > 3:
        raise _unpinned("custom number format")
    if x > 0 or (x == 0 and len(sections) < 3):
        section, sign, flip = sections[0], "", False
    elif x < 0 and len(sections) >= 2:
        section, sign, flip = sections[1], "", True
    elif x < 0:
        section, sign, flip = sections[0], "-", True
    else:
        section, sign, flip = sections[2], "", False
    m = _CUSTOM_SECTION.fullmatch(section)
    if m is None or any(ch not in _LITERALS for ch in m.group(1) + m.group(3)):
        raise _unpinned("custom number format")
    prefix, body, suffix = m.group(1), m.group(2), m.group(3)
    scale = 2 if "%" in prefix + suffix else 0
    int_part, _, frac_part = body.partition(".")
    grouping = "," in int_part
    min_int = int_part.count("0")
    min_frac = frac_part.count("0")
    max_frac = len(frac_part)
    magnitude = V.Number(abs(x), exact=(number.exact.lstrip("-") if number.exact is not None else None))
    whole, frac, _ = _fixed_parts(magnitude, max_frac, scale)
    if sign == "-" and not any(c != "0" for c in whole + frac):
        sign = ""  # a negative value that rounds to zero has no sign (measured)
    elif flip and len(sections) >= 2 and not any(c != "0" for c in whole + frac):
        raise _unpinned("custom number format section of a negative value that rounds to zero")
    frac = frac.rstrip("0")
    frac = frac + "0" * (min_frac - len(frac)) if len(frac) < min_frac else frac
    whole = whole.lstrip("0")
    if len(whole) < min_int:
        whole = "0" * (min_int - len(whole)) + whole
    group, decimal_sep, _ = _SYMBOLS[culture]
    if grouping:
        whole = _group(whole, group)
    text = whole + (decimal_sep + frac if frac else "")
    return sign + prefix + text + suffix


def _format_number(number: V.Number, fmt: Optional[str], culture: str) -> str:
    x = number.value
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    if fmt is None:
        return number_text_of(number)
    if fmt == "":
        raise _unpinned("empty number format")
    m = _STANDARD.fullmatch(fmt)
    if m is None:
        return _custom(number, fmt, culture)
    letter = m.group(1).upper()
    lower = m.group(1).islower()
    digits = m.group(2)
    prec = int(digits) if digits else None
    if prec is not None and prec > 99:
        raise _unpinned("number format precision above 99")
    dec, grp = (".", ",") if culture == _EN else (",", ".")
    if letter == "R":
        return number_text_of(number).replace(".", dec)
    if letter == "D":
        n = _integer_of(number)
        return ("-" if n < 0 else "") + str(abs(n)).zfill(prec or 1)
    if letter == "X":
        n = _integer_of(number)
        text = format(n + (2 ** 64 if n < 0 else 0), "x" if lower else "X")
        return text.zfill(prec or 1)
    if number.exact is None and x != 0 and x == math.floor(x) and 1e15 <= abs(x) < 2.0 ** 96:
        return number_text(x)
    if letter == "G":
        text = _general(number, prec or 0, lower)
        return text.replace(".", dec)
    if letter == "E":
        return _scientific(number, 6 if prec is None else prec, lower).replace(".", dec)
    places = 2 if prec is None else prec
    if letter == "F":
        whole, frac, neg = _fixed_parts(number, places)
        return ("-" if neg else "") + whole + (dec + frac if frac else "")
    if letter == "N":
        whole, frac, neg = _fixed_parts(number, places)
        return ("-" if neg else "") + _group(whole, grp) + (dec + frac if frac else "")
    if letter == "P":
        whole, frac, neg = _fixed_parts(number, places, 2)
        body = _group(whole, grp) + (dec + frac if frac else "")
        return ("-" if neg else "") + body + (" %" if culture == _DE else "%")
    if letter == "C":
        whole, frac, neg = _fixed_parts(number, places)
        body = _group(whole, grp) + (dec + frac if frac else "")
        if culture == _DE:
            return ("-" if neg else "") + body + " €"
        return "(" + "$" + body + ")" if neg else "$" + body
    raise _unpinned("number format")


def _number_to_text(value: MValue, fmt: MValue = V.Null(), culture: MValue = V.Null()) -> MValue:
    if isinstance(value, V.Null):
        return V.Null()
    x = _num(value)
    lang = _culture(culture)
    spec = None if isinstance(fmt, V.Null) else _text_arg(fmt)
    if spec is None and not _is_special(x):
        return V.Text(number_text_of(value).replace(".", _SYMBOLS[lang][1]))
    return V.Text(_format_number(value, spec, lang))


# ---- the table added to the stdlib --------------------------------------------

NUMBER_GLOBALS: dict = {
    "Number.E": V.Number(math.e),
    "Number.PI": V.Number(math.pi),
    "Number.NaN": V.Number(math.nan),
    "Number.PositiveInfinity": V.Number(math.inf),
    "Number.NegativeInfinity": V.Number(-math.inf),
    "Number.Epsilon": V.Number(5e-324),
    "RoundingMode.Up": V.Number(ROUNDING_MODES["Up"]),
    "RoundingMode.Down": V.Number(ROUNDING_MODES["Down"]),
    "RoundingMode.AwayFromZero": V.Number(ROUNDING_MODES["AwayFromZero"]),
    "RoundingMode.TowardZero": V.Number(ROUNDING_MODES["TowardZero"]),
    "RoundingMode.ToEven": V.Number(ROUNDING_MODES["ToEven"]),
    "Number.Abs": _native((("number", False),), _abs),
    "Number.Sign": _native((("number", False),), _sign_of),
    "Number.Sqrt": _native((("number", False),), _unary(_sqrt)),
    "Number.Exp": _native((("number", False),), _unary(_exp)),
    "Number.Ln": _native((("number", False),), _ln_of),
    "Number.Log10": _native((("number", False),), _log10_of),
    "Number.Log": _native((("number", False), ("base", True)), _log_of),
    "Number.Power": _native((("number", False), ("power", False)), _power_of),
    "Number.Mod": _native((("number", False), ("divisor", False)), _mod_of),
    "Number.IntegerDivide": _native((("number", False), ("divisor", False)), _integer_divide_of),
    "Number.Atan2": _native((("y", False), ("x", False)), _atan2_of),
    "Number.Sin": _native((("number", False),), _refusing("Number.Sin", _sin)),
    "Number.Cos": _native((("number", False),), _refusing("Number.Cos", _cos)),
    "Number.Tan": _native((("number", False),), _refusing("Number.Tan", _tan)),
    "Number.Asin": _native((("number", False),), _refusing("Number.Asin", _asin)),
    "Number.Acos": _native((("number", False),), _refusing("Number.Acos", _acos)),
    "Number.Atan": _native((("number", False),), _refusing("Number.Atan", _atan)),
    "Number.Sinh": _native((("number", False),), _refusing("Number.Sinh", _sinh)),
    "Number.Cosh": _native((("number", False),), _refusing("Number.Cosh", _cosh)),
    "Number.Tanh": _native((("number", False),), _refusing("Number.Tanh", _tanh)),
    "Number.Round": _native((("number", False), ("digits", True), ("roundingMode", True)), _round),
    "Number.RoundUp": _native((("number", False), ("digits", True)), _directed("ROUND_CEILING")),
    "Number.RoundDown": _native((("number", False), ("digits", True)), _directed("ROUND_FLOOR")),
    "Number.RoundTowardZero": _native((("number", False), ("digits", True)), _directed("ROUND_DOWN")),
    "Number.RoundAwayFromZero": _native((("number", False), ("digits", True)), _directed("ROUND_UP")),
    "Number.IsEven": _native((("number", False),), _is_even),
    "Number.IsOdd": _native((("number", False),), _is_odd),
    "Number.IsNaN": _native((("number", False),), _is_nan),
    "Number.Factorial": _native((("number", False),), _factorial),
    "Number.Combinations": _native((("n", False), ("k", False)), _combinations),
    "Number.Permutations": _native((("n", False), ("k", False)), _permutations),
    "Number.Random": _native((), _random),
    "Number.RandomBetween": _native((("low", False), ("high", False)), _random_between),
    "Number.BitwiseAnd": _native((("first", False), ("second", False)), _bitwise(lambda a, b: a & b)),
    "Number.BitwiseOr": _native((("first", False), ("second", False)), _bitwise(lambda a, b: a | b)),
    "Number.BitwiseXor": _native((("first", False), ("second", False)), _bitwise(lambda a, b: a ^ b)),
    "Number.BitwiseNot": _native((("value", False),), _bitwise_not),
    "Number.BitwiseShiftLeft": _native((("value", False), ("count", False)), _shift(True)),
    "Number.BitwiseShiftRight": _native((("value", False), ("count", False)), _shift(False)),
    "Number.From": _native((("value", False), ("culture", True)), _number_from),
    "Number.FromText": _native((("text", False), ("culture", True)), _number_from_text),
    "Number.ToText": _native((("value", False), ("format", True), ("culture", True)), _number_to_text),
    "Double.From": _native((("value", False), ("culture", True)), _double_from),
    "Single.From": _native((("value", False), ("culture", True)), _single_from),
    "Decimal.From": _native((("value", False), ("culture", True)), _decimal_from),
    "Currency.From": _native((("value", False), ("culture", True)), _currency_from),
    "Percentage.From": _native((("value", False), ("culture", True)), _decimal_from),
    "Logical.From": _native((("value", False),), _logical_from),
    "Logical.FromText": _native((("text", False),), _logical_from_text),
    "Logical.ToText": _native((("value", False),), _logical_to_text),
}

for _name in ("Int8", "Int16", "Byte", "Int32", "Int64"):
    _bits, _lo, _hi, _small = _int_bits(_name)
    NUMBER_GLOBALS[f"{_name}.From"] = _native((("value", False), ("culture", True), ("roundingMode", True)),
                                              _integer_from(_bits, _lo, _hi, _small))
