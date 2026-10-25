"""DAX math, trigonometry and statistics functions, matching Power BI Desktop 2.157.879.0.

Scalar functions take already-evaluated arguments (``None`` is BLANK).  Compared live through
``tools/dax_battery_math.json``; every error below is one Power BI raises.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, ROUND_UP
import math
import random

from analytics_studio import dax_typed

_FAIL = "An argument of function '{}' has the wrong data type or the result is too large or too small."


def _fail(function: str) -> Exception:
    return dax_typed._error(_FAIL.format(function))


def _double(value: float, function: str) -> Decimal:
    if math.isnan(value) or math.isinf(value):
        raise _fail(function)
    return Decimal(repr(value)) if value != 0 else Decimal(0)


def _to_float(value: object, function: str) -> float:
    number = dax_typed.to_number(value)
    if not number.is_finite():
        raise _fail(function)
    return float(number)


def _round_digits(value: Decimal, digits: int, rounding: str) -> Decimal:
    if not value.is_finite():
        raise _fail("ROUND")
    context = dax_typed.QUIET.copy()
    context.prec = 60
    quantum = Decimal(1).scaleb(-digits)
    if digits >= 0:
        return value.quantize(quantum, rounding=rounding, context=context)
    shifted = value.scaleb(digits)
    return shifted.quantize(Decimal(1), rounding=rounding, context=context).scaleb(-digits)


def rounding_function(function: str, args: list[object]) -> Decimal | None:
    """ROUND, ROUNDUP and ROUNDDOWN: blank value is blank, blank digits are 0, fractional digits round."""
    if args[0] is None:
        return None
    number = dax_typed.to_number(args[0])
    digits = dax_typed.whole(args[1], function)
    mode = {"ROUND": ROUND_HALF_UP, "ROUNDUP": ROUND_UP, "ROUNDDOWN": ROUND_DOWN}[function]
    if not number.is_finite():
        if function == "ROUNDDOWN":
            return number  # ROUNDDOWN of Infinity is Infinity, an error value
        raise _fail(function)
    if digits > 40:
        return number  # nothing is left to round
    if digits < -40:
        return Decimal(0)
    result = _round_digits(number, digits, mode)
    return Decimal(0) if result == 0 else result


def _next_multiple(value: Decimal, base: int) -> Decimal:
    """EVEN / ODD: round away from zero to the next even / odd whole number."""
    magnitude = abs(value).to_integral_value(rounding=ROUND_UP)
    if magnitude % 2 != (0 if base == 2 else 1):
        magnitude += 1
    return -magnitude if value < 0 else magnitude


_BLANK_IN_BLANK_OUT = {"ASIN", "ASINH", "ATAN", "ATANH", "DEGREES", "RADIANS", "SIN", "SINH", "TAN", "TANH", "SQRTPI", "EVEN"}


def math_function(function: str, args: list[object]) -> object:
    """Scalar math: returns the DAX result of an already-evaluated call."""
    if function in _BLANK_IN_BLANK_OUT and args and args[0] is None:
        return None
    if function == "QUOTIENT" and args[0] is None:
        return None
    if function == "LOG" and len(args) > 1 and args[1] is None:
        raise _fail(function)
    if function in {"ROUND", "ROUNDUP", "ROUNDDOWN"}:
        return rounding_function(function, args)
    if function == "PI":
        return Decimal(repr(math.pi))
    if function == "RAND":
        return Decimal(repr(random.random()))
    if function == "RANDBETWEEN":
        low, high = dax_typed.whole(args[0], function), dax_typed.whole(args[1], function)
        if low > high:
            raise _fail(function)
        return Decimal(random.randint(low, high))
    if function == "MROUND":
        if args[0] is None:
            return None
        number = dax_typed.to_number(args[0])
        multiple = dax_typed.to_number(args[1])
        if multiple == 0:
            return Decimal(0)
        if (number > 0 and multiple < 0) or (number < 0 and multiple > 0):
            raise _fail(function)
        steps = (number / multiple).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        result = steps * multiple
        return Decimal(0) if result == 0 else result
    if function in {"ISEVEN", "ISODD"}:
        number = dax_typed.to_number(args[0])
        remainder = number % 2
        return (remainder == 0) if function == "ISEVEN" else (remainder != 0)
    if args[0] is None and function in {"EVEN", "ODD"}:
        return Decimal(0) if function == "EVEN" else Decimal(1)
    if function in {"EVEN", "ODD"}:
        return _next_multiple(dax_typed.to_number(args[0]), 2 if function == "EVEN" else 1)
    if function in {"LOG", "LOG10"}:
        number = dax_typed.to_number(args[0])
        base = dax_typed.to_number(args[1]) if len(args) > 1 and args[1] is not None else Decimal(10)
        if number <= 0 or base <= 0:
            error = _fail(function)
            error.infinity = args[0] is None  # LOG(BLANK()) is -Infinity, an error value
            raise error
        if base == 1:
            raise dax_typed._error("Division by zero has occurred when evaluating function 'LOG'.")
        value = math.log(float(number)) / math.log(float(base)) if function == "LOG" and len(args) > 1 else math.log10(float(number))
        return _double(round(value, 12) if abs(value - round(value)) < 1e-12 else value, function)
    if function in _TRIG:
        return _trig(function, _to_float(args[0], function))
    if function == "FACT":
        number = dax_typed.to_number(args[0])
        if number < 0 or number >= 171:
            raise _fail(function)
        return Decimal(math.factorial(int(number)))
    if function in {"GCD", "LCM"}:
        if all(value is None for value in args):
            return None  # Power BI: GCD(BLANK(),BLANK()) is blank
        a, b = (_round_half_away(value, function) for value in args)
        if a < 0 or b < 0 or a > _MAX_EXACT_INTEGER or b > _MAX_EXACT_INTEGER:
            raise _fail(function)
        result = math.gcd(a, b) if function == "GCD" else (0 if a == 0 or b == 0 else a * b // math.gcd(a, b))
        if result > _MAX_EXACT_INTEGER:
            raise _fail(function)
        return Decimal(result)
    if function == "QUOTIENT":
        numerator, denominator = (dax_typed.to_number(value) for value in args)
        if denominator == 0:
            raise dax_typed._error("Division by zero has occurred when evaluating function 'QUOTIENT'.")
        return (numerator / denominator).to_integral_value(rounding=ROUND_DOWN)
    if function == "SQRTPI":
        number = dax_typed.to_number(args[0])
        if number < 0:
            raise _fail(function)
        return _double(math.sqrt(float(number) * math.pi), function)
    if function == "CURRENCY":
        if args[0] is None:
            return None
        return dax_typed.to_number(args[0]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if function in {"COMBIN", "COMBINA", "PERMUT"}:
        n, k = (_round_half_away(value, function) for value in args)
        if n < 0 or k < 0 or (function != "COMBINA" and k > n) or (function == "COMBINA" and n == 0 and k > 0):
            raise _fail(function)
        top = n + k - 1 if function == "COMBINA" else n
        if n >= _MAX_COMBINATORICS_ARGUMENT or top >= _MAX_COMBINATORICS_ARGUMENT:
            raise _fail(function)
        if function == "COMBINA" and k == 0:
            return Decimal(1)
        # estimate the size first so an enormous request fails at once instead of building a huge integer
        log10_size = (
            math.lgamma(top + 1) - math.lgamma(k + 1) - math.lgamma(top - k + 1) if function != "PERMUT"
            else math.lgamma(n + 1) - math.lgamma(n - k + 1)
        ) / math.log(10)
        if log10_size > 309:
            raise _fail(function)
        result = math.perm(n, k) if function == "PERMUT" else math.comb(top, k)
        try:
            float(result)
        except OverflowError:
            raise _fail(function) from None
        return Decimal(result)
    raise _fail(function)


_MAX_EXACT_INTEGER = 2 ** 53  # GCD and LCM take and return doubles
_MAX_COMBINATORICS_ARGUMENT = 2147483647


def _round_half_away(value: Any, function: str) -> int:
    """Power BI rounds the integer arguments of GCD, LCM, COMBIN, COMBINA and PERMUT half away from zero, as
    floor(x + 0.5) on a double (FACT truncates)."""
    number = float(dax_typed.to_number(value))
    if math.isnan(number) or math.isinf(number):
        raise _fail(function)
    # at 2**52 and above every double is already a whole number (adding 0.5 would round to even)
    rounded = int(abs(number)) if abs(number) >= 2 ** 52 else math.floor(abs(number) + 0.5)
    return -rounded if number < 0 else rounded


_TRIG = {
    "SIN": math.sin, "COS": math.cos, "TAN": math.tan, "ASIN": math.asin, "ACOS": math.acos, "ATAN": math.atan,
    "SINH": math.sinh, "COSH": math.cosh, "TANH": math.tanh, "ASINH": math.asinh, "ACOSH": math.acosh,
    "ATANH": math.atanh, "DEGREES": math.degrees, "RADIANS": math.radians,
}


def _trig(function: str, value: float) -> Decimal:
    try:
        return _double(_TRIG[function](value), function)
    except (ValueError, OverflowError) as exc:
        raise _fail(function) from exc


MATH_ARITY = {
    "ROUNDUP": (2, 2), "ROUNDDOWN": (2, 2), "MROUND": (2, 2), "ISEVEN": (1, 1), "ISODD": (1, 1), "EVEN": (1, 1),
    "ODD": (1, 1), "LOG": (1, 2), "LOG10": (1, 1), "PI": (0, 0), "FACT": (1, 1), "GCD": (2, 2), "LCM": (2, 2),
    "QUOTIENT": (2, 2), "SQRTPI": (1, 1), "CURRENCY": (1, 1), "COMBIN": (2, 2), "COMBINA": (2, 2), "PERMUT": (2, 2),
    "RAND": (0, 0), "RANDBETWEEN": (2, 2), "ROUND": (2, 2), **{name: (1, 1) for name in _TRIG},
}

# ------------------------------------------------------------------------------------------ statistics

_STAT_COLUMN = {"STDEV.S", "STDEV.P", "VAR.S", "VAR.P", "GEOMEAN"}
STAT_COLUMN_FUNCTIONS = _STAT_COLUMN | {"AVERAGEA", "MAXA", "MINA"}
STAT_PERCENTILE_COLUMN = {"PERCENTILE.INC", "PERCENTILE.EXC"}
STAT_ITERATORS = {
    "STDEVX.S", "STDEVX.P", "VARX.S", "VARX.P", "GEOMEANX", "MEDIANX", "PERCENTILEX.INC", "PERCENTILEX.EXC", "PRODUCTX",
}


def statistic(function: str, values: list[Decimal], k: Decimal | None = None) -> Decimal | None:
    """Statistic over the non-blank numbers of a column or iterator; None when there is nothing to compute."""
    name = {"PERCENTILEX.INC": "PERCENTILE.INC", "PERCENTILEX.EXC": "PERCENTILE.EXC", "STDEVX.S": "STDEV.S",
            "STDEVX.P": "STDEV.P", "VARX.S": "VAR.S", "VARX.P": "VAR.P", "GEOMEANX": "GEOMEAN", "MEDIANX": "MEDIAN",
            "PRODUCTX": "PRODUCT"}.get(function, function)
    if not values:
        return None
    count = len(values)
    if name == "AVERAGEA":
        return sum(values, Decimal(0)) / count
    if name == "MAXA":
        return max(values)
    if name == "MINA":
        return min(values)
    if name == "PRODUCT":
        product = Decimal(1)
        for value in values:
            product *= value
        return product
    if name == "MEDIAN":
        ordered = sorted(values)
        middle = count // 2
        return ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    if name == "GEOMEAN":
        if any(value == 0 for value in values):
            return Decimal(0)
        return _double(math.exp(sum(math.log(abs(float(value))) for value in values) / count), function)
    if name in {"VAR.S", "VAR.P", "STDEV.S", "STDEV.P"}:
        sample = name.endswith(".S")
        if sample and count < 2:
            error = dax_typed._error(f"Division by zero has occurred when evaluating function '{function}'.")
            error.sample_statistic_nan = True  # NaN in Power BI (iteration 88); see the measure-level handling in measures.resolve
            raise error
        mean = sum(values, Decimal(0)) / count
        variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / (count - 1 if sample else count)
        return variance if name.startswith("VAR") else variance.sqrt()
    if name in {"PERCENTILE.INC", "PERCENTILE.EXC"}:
        if k is None:
            raise _fail(function)
        ordered = sorted(values)
        if name == "PERCENTILE.INC":
            if not Decimal(0) <= k <= Decimal(1):
                raise dax_typed._error("The percentile value should be in the range 0..1, inclusive.")
            position = k * (count - 1)
        else:
            if not Decimal(1) / (count + 1) <= k <= Decimal(count) / (count + 1):
                raise dax_typed._error(
                    "The percentile value should be in the range 1/(N+1)..N/(N+1) inclusive, where N is the number of data values."
                )
            position = k * (count + 1) - 1
        low = int(position.to_integral_value(rounding=ROUND_FLOOR))
        fraction = position - low
        if low + 1 >= count:
            return ordered[-1] if low >= count - 1 else ordered[low]
        return ordered[low] + (ordered[low + 1] - ordered[low]) * fraction
    raise _fail(function)
