"""DAX math, trigonometry and statistics functions, matching Power BI Desktop 2.157.879.0.

Scalar functions take already-evaluated arguments (``None`` is BLANK).  Compared live through
``tools/dax_battery_math.json``; every error below is one Power BI raises.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
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
        if args[1] is not None:
            dax_typed.whole(args[1], function)  # Task 20 F4: a BLANK number still reads its digits; an Infinity, a NaN or a text there is the error
        return None
    number = dax_typed.to_number(args[0])
    digits = dax_typed.whole(args[1], function)
    mode = {"ROUND": ROUND_HALF_UP, "ROUNDUP": ROUND_UP, "ROUNDDOWN": ROUND_DOWN}[function]
    if not number.is_finite():
        if function == "ROUNDDOWN" and number == Decimal("Infinity"):
            return Decimal("NaN")  # Part E: ROUNDDOWN of +Infinity is NaN (measured)
        if function == "ROUNDDOWN":
            return number  # ROUNDDOWN of Infinity is Infinity, an error value
        raise _fail(function)
    if abs(number) >= Decimal("1E16"):
        return number  # Part E: a finite value beyond 1E16 is returned unchanged by ROUND, ROUNDUP and ROUNDDOWN, any digits (measured to 1E300 and 1E308)
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
        dax_typed.to_number(args[1])  # a BLANK numerator still reads the divisor: a text is the error, an Infinity, a NaN or a zero gives BLANK
        if args[1] is None:
            raise dax_typed._error("Division by zero has occurred when evaluating function 'QUOTIENT'.")  # only an actual BLANK divisor
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
            dax_typed.to_number(args[1])  # Task 20 F4: a BLANK number still reads the multiple; a text there is the error
            return None
        number = dax_typed.to_number(args[0])
        multiple = dax_typed.to_number(args[1])
        if multiple == 0:
            return Decimal(0)
        if (number > 0 and multiple < 0) or (number < 0 and multiple > 0):
            raise _fail(function)
        if abs(number) >= 2 ** 53:
            # Part D: from 2^53 the quotient and the product are rounded to doubles in Power BI (MROUND(2^63-1024,3) is the error, its double product being 2^63).
            # Below 2^53 the exact rule below matches every measured row but MROUND(5E15,3), which Power BI gives as 5000000000000002 (exact ...001; wrong here as on main).
            quotient = float(number) / float(multiple)
            if not math.isfinite(quotient):
                raise dax_typed.refusal("MROUND of a quotient beyond the Double range is not modelled by the local engine.")
            whole = math.floor(abs(quotient) + 0.5)
            product = float(-whole if quotient < 0 else whole) * float(multiple)
            if not math.isfinite(product) or abs(product) >= 2 ** 63:
                raise dax_typed._error("The result of a conversion or arithmetic operation is either too large or too small.")
            return Decimal(0) if product == 0 else Decimal(product)
        steps = (number / multiple).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        result = steps * multiple
        if abs(result) >= 2 ** 63:  # Part D: an Integer result beyond the 64-bit range is the conversion error
            raise dax_typed._error("The result of a conversion or arithmetic operation is either too large or too small.")
        return Decimal(0) if result == 0 else result
    if function in {"DEGREES", "RADIANS", "TANH", "ATAN", "EVEN", "ODD", "ISEVEN", "ISODD"} and args[0] is not None:
        number = dax_typed.to_number(args[0])
        if not number.is_finite():  # Task 20 F3: Power BI measures these (not an error) for an Infinity or a NaN
            if function in {"DEGREES", "RADIANS", "ODD"}:
                return Decimal(0)
            if function == "TANH":
                return Decimal(1)
            if function == "EVEN":
                return number  # EVEN gives x back
            if function == "ATAN":
                if number.is_nan():
                    raise dax_typed.refusal("ATAN of NaN is an unpredictable value in Power BI and is not modelled by the local engine.")
                return _double(math.atan(float(number)), function)
            raise _fail(function)  # ISEVEN / ISODD of an Infinity or a NaN
    if function in {"ISEVEN", "ISODD"}:
        number = dax_typed.to_number(args[0])
        remainder = int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP)) % 2  # to the nearest whole number first: ISEVEN(2.5) is False, ISEVEN(TIME(6,0,0)) True (live Power BI)
        return (remainder == 0) if function == "ISEVEN" else (remainder != 0)
    if args[0] is None and function in {"EVEN", "ODD"}:
        return Decimal(0) if function == "EVEN" else Decimal(1)
    if function in {"EVEN", "ODD"}:
        number = dax_typed.to_number(args[0])
        if abs(number) >= Decimal("1E16"):
            return number  # Part E: EVEN and ODD of a finite value from 1E16 up are the value itself (EVEN(1E300) is 1E+300, ODD(9.22E18) is 9.22E+18, ODD(1E17+0.5) is 1E+17, measured)
        return _next_multiple(number, 2 if function == "EVEN" else 1)
    if function in {"LOG", "LOG10"}:
        number = dax_typed.to_number(args[0])
        base = dax_typed.to_number(args[1]) if len(args) > 1 and args[1] is not None else Decimal(10)
        if args[0] is None and (len(args) == 1 or args[1] is not None):
            return Decimal("-Infinity")  # LOG(BLANK()) and LOG(BLANK(),b) are -Infinity for any real base, as LN(BLANK()) is; a BLANK base stays an error
        if number <= 0 or base <= 0 or base.is_infinite():  # an infinite base is an error like a zero base (LOG(1/0,1/0) must not crash); a BLANK number returned above
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
        if not numerator.is_finite() or denominator.is_nan():  # Task 20 F3: an Infinity or NaN numerator, or a NaN divisor, is the error (an Infinity divisor gives 0)
            raise _fail(function)
        if denominator == 0:
            raise dax_typed._error("Division by zero has occurred when evaluating function 'QUOTIENT'.")
        quotient = (numerator / denominator).to_integral_value(rounding=ROUND_DOWN)
        if abs(quotient) >= 2 ** 63:  # Part D: an Integer result beyond the 64-bit range is the conversion error
            raise dax_typed._error("The result of a conversion or arithmetic operation is either too large or too small.")
        return quotient
    if function == "SQRTPI":
        number = dax_typed.to_number(args[0])
        if number < 0:
            raise _fail(function)
        return _double(math.sqrt(float(number) * math.pi), function)
    if function == "CURRENCY":
        if args[0] is None:
            return None
        if isinstance(args[0], str):
            return text_to_currency(dax_typed.to_number(args[0]))  # Task 21 Part C: a text is read as a Currency from its exact digits
        return to_currency(dax_typed.to_number(args[0]))
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


def to_currency(number: Decimal) -> Decimal:
    """Live Power BI (Task 14 review): ten-thousandths as a double multiply, then half away from zero: 10.00005 gives 10.0001, 20.12345 gives 20.1234."""
    if not number.is_finite() or abs(number) >= Decimal("1E14"):
        return number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if number.is_finite() else number
    return (Decimal(float(number) * 10000.0).quantize(Decimal(1), rounding=ROUND_HALF_UP) / 10000).quantize(Decimal("0.0001"))


_CURRENCY_MAX = Decimal("922337203685477.5807")  # the Currency type's range, both ways


def text_to_currency(number: Decimal) -> Decimal:
    """Task 21 Part C: a text read as a Currency is rounded half to even from its exact digits (CURRENCY("0.00005") is 0);
    beyond the Currency range, or not finite, it is the 'Out of present range' error."""
    if not number.is_finite() or abs(number) > _CURRENCY_MAX:
        raise dax_typed._error("The following system error occurred: Out of present range.")
    return number.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


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
        if product.is_finite() and abs(product) > Decimal("1.7976931348623157E+308"):
            return Decimal("Infinity") if product > 0 else Decimal("-Infinity")  # Part B: beyond the double range is Infinity
        return product
    if name == "MEDIAN":
        ordered = sorted(values)
        middle = count // 2
        return ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    if name == "GEOMEAN":
        if any(value == 0 for value in values):
            return Decimal(0)
        magnitude = _double(math.exp(sum(math.log(abs(float(value))) for value in values) / count), function)
        # live Power BI (Task 11 review): the geometric mean of the absolute values, negative when the product is (an odd number of negative values)
        return -magnitude if sum(1 for value in values if value < 0) % 2 else magnitude
    if name in {"VAR.S", "VAR.P", "STDEV.S", "STDEV.P"}:
        sample = name.endswith(".S")
        if sample and count < 2:
            error = dax_typed._error(f"Division by zero has occurred when evaluating function '{function}'.")
            error.sample_statistic_nan = True  # NaN in Power BI (iteration 88); see the measure-level handling in measures.resolve
            raise error
        if count > 1 and len(set(values)) == 1 and values[0] != values[0].to_integral_value():
            # live Power BI (Task 11 review): the spread of one repeated fraction is float noise (8.4E-08), not 0
            raise dax_typed.refusal(f"{function} of one repeated fraction carries float noise that the local engine does not reproduce.")
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
