"""DAX math, trigonometry and statistics functions, matching Power BI Desktop 2.157.879.0.

Scalar functions take already-evaluated arguments (``None`` is BLANK).  Compared live through
``tools/dax_battery_math.json``; every error below is one Power BI raises.
"""

from __future__ import annotations

from decimal import Context, Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, localcontext
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
    number = dax_typed.to_number(args[0], dates=True)
    if number.is_finite() and abs(number) > Decimal("1.7E308"):
        raise dax_typed.refusal(f"{function} of a number within 5% of the Double maximum is not modelled by the local engine (ROUND(1.7976931348623157E308,1) is NaN, measured).")
    if function == "ROUND":
        number = dax_typed.int64_through_double(number)  # Task 74 Part B: ROUND of 9223372036854775807 is the conversion error (measured)
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


def _mround_fraction(number: Decimal, multiple: Decimal) -> Decimal:
    """Task 145 family A (measured): MROUND with a fractional multiple of either sign is worked in binary doubles, as Task 144 does for FLOOR and CEILING.
    The magnitudes: the quotient rounded to a double, then to 15 significant digits, a tie away from zero, then the whole step times the multiple in double
    (MROUND(7,1E-5)-7 is 8.88178419700125E-16, MROUND(0.3,0.1)-0.3 is 5.55111512312578E-17, MROUND(3,0.1)-3 is 0). The exact Decimal is kept only when it is the very same double."""
    if number == 0:
        return Decimal(0)
    sign = -1 if number < 0 else 1  # the result takes the sign of the number (a negative multiple goes with a negative number)
    magnitude, step = abs(number), abs(multiple)
    quotient = float(magnitude) / float(step)
    if not math.isfinite(quotient) or float(step) == 0:
        raise dax_typed.refusal("MROUND with a fractional multiple beyond the Double range is not modelled by the local engine.")
    with localcontext() as fifteen:  # the quotient at 15 significant digits, a tie away from zero
        fifteen.prec = 60
        exact_q = Decimal(quotient)
        quantum = Decimal(1).scaleb(exact_q.adjusted() - 14)
        quotient15 = (exact_q / quantum).to_integral_value(rounding=ROUND_HALF_UP) * quantum
    steps = quotient15.to_integral_value(rounding=ROUND_HALF_UP)
    doubled = float(steps) * float(step)
    with localcontext() as exact:
        exact.prec = 100
        exact_answer = (magnitude / step).to_integral_value(rounding=ROUND_HALF_UP) * step
    value = exact_answer if float(exact_answer) == doubled else Decimal(doubled)
    if value == 0:
        return Decimal(0)
    return -value if sign < 0 else value


_BLANK_IN_BLANK_OUT = {"ASIN", "ASINH", "ATAN", "ATANH", "DEGREES", "RADIANS", "SIN", "SINH", "TAN", "TANH", "SQRTPI", "EVEN"}


def math_function(function: str, args: list[object]) -> object:
    """Scalar math: returns the DAX result of an already-evaluated call."""
    if function in {"ROUNDUP", "ROUNDDOWN", "MROUND", "EVEN", "ODD", "QUOTIENT"}:
        for a in args:
            if isinstance(a, (int, float, Decimal)):
                d = Decimal(a)
                if d.is_finite() and 0 < abs(d) < dax_typed.DBL_MIN:
                    raise dax_typed.refusal(f"{function} with a subnormal argument is not modelled by the local engine.")
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
            quotient = float(number) / float(multiple)
            if not math.isfinite(quotient):
                raise dax_typed.refusal("MROUND of a quotient beyond the Double range is not modelled by the local engine.")
            # a double quotient from 2^52 up is already a whole number: adding 0.5 would round it to even (3^34+1 over 3: ...523 is not ...524), so it is taken as it is
            whole = math.floor(abs(quotient)) if abs(quotient) >= 2 ** 52 else math.floor(abs(quotient) + 0.5)
            product = float(-whole if quotient < 0 else whole) * float(multiple)
            if not math.isfinite(product) or abs(product) >= 2 ** 63:
                raise dax_typed._error("The result of a conversion or arithmetic operation is either too large or too small.")
            return Decimal(0) if product == 0 else Decimal(product)
        if abs(number) >= 2 ** 52:  # measured: from 2^52 a whole multiple gives an even result (an odd one goes up by 1)
            m_f = float(multiple)
            q = float(number) / m_f
            steps = int(math.floor(abs(q) + 0.5))
            if multiple == multiple.to_integral_value():
                prod = steps * abs(int(multiple))
                if prod % 2 != 0 and (abs(number) >= Decimal("5E15") or prod >= 2 ** 52):
                    # Task 55 (measured, 13 rows): an odd product from 2^52 up goes up by one (MROUND(4.6E15,3) is 4600000000000000); an odd product below 2^52
                    # stays odd (MROUND(2^52,3) is 4503599627370495, MROUND(4503599627370497,13) is 4503599627370493)
                    prod += 1
                result = Decimal(-prod if number < 0 else prod)
            else:
                prod = float(steps) * abs(m_f)
                result = Decimal(-prod if number < 0 else prod)
            if abs(result) >= 2 ** 63:
                raise dax_typed._error("The result of a conversion or arithmetic operation is either too large or too small.")
            return Decimal(0) if result == 0 else result
        if multiple != multiple.to_integral_value() and abs(number) / abs(multiple) < Decimal("1E15"):
            result = _mround_fraction(number, multiple)  # Task 145 family A: a fractional multiple is worked in doubles (a quotient from 1E15 up keeps the exact path, measured by the locked MROUND(4E15,1.5) answers)
        else:
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
        if isinstance(args[0], str) and abs(number) >= dax_typed._INT64_LIMIT:
            # Task 74 Part B: a number text is a Double and ISEVEN / ISODD read it as an Int64: 2^63 or more is a range error (measured for
            # "9223372036854775808", "1e400", "1.8e308"; the text of -2^63 itself is not measured and is refused)
            if number < 0 and float(number) == -float(dax_typed._INT64_LIMIT):
                raise dax_typed.refusal("ISEVEN and ISODD of the text -9223372036854775808 are not modelled by the local engine.")
            raise dax_typed._error("The following system error occurred: Out of present range.")
        if not dax_typed.is_int64_form(number) and number < 0 and float(number) == -float(dax_typed._INT64_LIMIT):
            # the literal -9223372036854775808 reads as the Double -9.223372036854776E+18: the conversion error (measured)
            raise dax_typed._error("The result of a conversion or arithmetic operation is either too large or too small.")
        if dax_typed.is_int64_form(number) and 2 ** 53 <= abs(number) <= dax_typed._INT64_LIMIT:
            number = Decimal(float(number))  # an Int64 from 2^53 up reads as its Double, always even: ISEVEN(9223372036854775807), ISEVEN(-9223372036854775807)
            # and ISEVEN of the wrapped -2^63 are True (measured)
        currency_text = isinstance(args[0], str) and "$" in args[0]  # Task 74 (t74d, t74e): a currency text goes to the whole number half to even (ISEVEN("$12.5") is True, ISEVEN("$0.5") True)
        remainder = int(number.quantize(Decimal(1), rounding=ROUND_HALF_EVEN if currency_text else ROUND_HALF_UP)) % 2  # to the nearest whole number first: ISEVEN(2.5) is False, ISEVEN(TIME(6,0,0)) True (live Power BI)
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
        if abs(numerator) >= 2 ** 53:
            q = float(numerator) / float(denominator)
            quotient = Decimal(int(q))
        else:
            quotient = (numerator / denominator).to_integral_value(rounding=ROUND_DOWN)
        if quotient.is_zero():
            quotient = Decimal(0)  # an Integer has no negative zero (SIGN(QUOTIENT(5E-320,-1)) is 0, measured)
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


_PI_QUARTER_EXACT = Decimal("3.14159265358979323846264338327950288419716939937510582097494459") / 4
_SQRT_HALF_DOUBLE = math.sqrt(0.5)
# Task 148 family B (measured): the engine reduces by whole multiples of the double pi/4 and picks the wrong octant for k mod 8 in {1, 3, 4, 6}
_TRIG_OCTANT_SIN = (0.0, _SQRT_HALF_DOUBLE, 1.0, _SQRT_HALF_DOUBLE, 0.0, -_SQRT_HALF_DOUBLE, -1.0, -_SQRT_HALF_DOUBLE)
_TRIG_OCTANT_COS = (1.0, _SQRT_HALF_DOUBLE, 0.0, -_SQRT_HALF_DOUBLE, -1.0, -_SQRT_HALF_DOUBLE, 0.0, _SQRT_HALF_DOUBLE)
_TRIG_TINY_LIMIT_ARGUMENT = 10.0  # Task 148 family C: the tiny-result refusal applies below this |x|; larger arguments are the known limits (saved answers)
_TRIG_NEAR_ULPS = 2  # Task 148 family B: a non-exact argument this many ulps from a multiple of pi/4 is refused


def _exact_quarter_pi_octant(function: str, value: float) -> Decimal | None:
    """Task 148 family B: SIN, COS, TAN at an exact double multiple k * (double pi/4), k != 0, from the engine's octant choice; None otherwise."""
    magnitude = abs(value)
    ratio = magnitude / (math.pi / 4)
    if ratio == 0 or ratio != math.floor(ratio):
        return None
    k = int(ratio)
    octant = (k + 1 if k % 8 in (1, 3, 4, 6) else k) % 8
    sine, cosine = _TRIG_OCTANT_SIN[octant], _TRIG_OCTANT_COS[octant]
    if function == "SIN":
        return _double(sine if value >= 0 else -sine, function)
    if function == "COS":
        return _double(cosine, function)
    if cosine == 0:
        raise dax_typed._error(f"Division by zero has occurred when evaluating function '{function}'.")
    return _double((sine / cosine) * (1 if value >= 0 else -1), function)


def _near_quarter_pi(value: float) -> bool:
    """Task 148 family B: a non-exact argument within _TRIG_NEAR_ULPS ulps of a nonzero whole multiple of pi/4 (the true pi/4)."""
    if value == 0:
        return False
    with localcontext() as ctx:
        ctx.prec = 80
        exact = Decimal(value)
        multiple = round(exact / _PI_QUARTER_EXACT)
        return multiple != 0 and abs(exact - multiple * _PI_QUARTER_EXACT) <= _TRIG_NEAR_ULPS * Decimal(math.ulp(value))


def trig_unreliable(function: str, value: float) -> bool:
    """Task 148 families B and C (measured): True where the local engine has no Power BI answer for SIN, COS or TAN.

    Family B: a non-exact argument within a couple of ulps of a nonzero multiple of pi/4 (SIN(4.71238898038469) is -0.707106781186548).
    Family C: pi/4 < |x| < 10 and the tiny sine or cosine behind the result is below |x| * 1E-4, where Power BI's argument reduction
    error (about |x| * 1E-16) shows in the digits (COS(1.5707963267949) is -3.5527136788005E-15 in Power BI).
    """
    if not math.isfinite(value) or value == 0:
        return False
    if _near_quarter_pi(value):
        return True
    if abs(value) <= math.pi / 4 or abs(value) >= _TRIG_TINY_LIMIT_ARGUMENT:
        return False
    limit = abs(value) * 1e-4
    sine, cosine = math.sin(value), math.cos(value)
    if function == "SIN":
        return abs(sine) < limit
    if function == "COS":
        return abs(cosine) < limit
    return abs(sine) < limit or abs(cosine) < limit  # TAN: a tiny sine or a tiny cosine


def _trig(function: str, value: float) -> Decimal:
    if function in {"SIN", "COS", "TAN"} and abs(value) >= 134217728:
        raise _fail(function)
    if function in {"SIN", "COS", "TAN"}:
        exact_multiple = _exact_quarter_pi_octant(function, value)
        if exact_multiple is not None:
            return exact_multiple  # Task 148 family B: the engine's own octant value (or its division by zero)
        if trig_unreliable(function, value):
            raise dax_typed.refusal(f"{function} at an argument near a multiple of pi/4 or with a tiny result is not modelled by the local engine.")
    if function in {"ASINH", "ACOSH"}:  # both square the value, which overflows above about 1.34E154
        try:
            sq = value * value
            if math.isinf(sq):
                raise _fail(function)
        except OverflowError:
            raise _fail(function)
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


def _interpolate(low: Decimal, high: Decimal, fraction: Decimal) -> Decimal:
    """low + (high - low) * fraction for low <= high, either of them possibly an Infinity (live Power BI, Task 39 review: equal ends or a zero
    fraction give the end itself; -Infinity + Infinity is the negative default NaN; a finite low with an Infinity high is that Infinity)."""
    if fraction == 0 or low == high:
        return low
    if low.is_finite() and high.is_finite():
        return low + (high - low) * fraction
    if low == Decimal("-Infinity"):
        return Decimal("-NaN")
    return high


_STATISTIC_NAMES = {"VARX.S": "VAR.S", "VARX.P": "VAR.P", "STDEVX.S": "STDEV.S", "STDEVX.P": "STDEV.P"}


def double_statistic(function: str, values: list[Decimal]) -> Decimal:
    """VAR / STDEV of the rows in Power BI's double arithmetic (Task 47): the rows are added in row order, as doubles.

    Live Power BI: VAR.P is the mean of the squares less the square of the mean; VAR.S is the sum of squares less the square of the
    sum over the count, divided by count - 1 (so one repeated fraction gives float noise, 6.3 x 3 gives 7.1E-15, and 0 for VAR.P);
    STDEV is the square root of that variance in double.  Rows that all repeat one value add it as count x value (the sum of squares
    as (value x value) x count), measured on 78 repeated fractions; other rows are added one at a time in row order.
    """
    name = _STATISTIC_NAMES.get(function, function)
    count = len(values)
    numbers = [float(value) for value in values]
    if all(number == numbers[0] for number in numbers):
        total = numbers[0] * count
        squares = numbers[0] * numbers[0] * count
    else:
        total = 0.0
        squares = 0.0
        for number in numbers:
            total += number
            squares += number * number
    if name.endswith(".S"):
        variance = (squares - total * total / count) / (count - 1)
    else:
        mean = total / count
        variance = squares / count - mean * mean
    if variance < 0:
        variance = 0.0  # live Power BI (Task 47): a spread that rounds below zero (VARX.P of 0.1 x 3 is -1.7E-18 in double) is 0
    if name.startswith("STDEV"):
        variance = math.sqrt(variance)
    if variance == 0:
        return Decimal(0)
    return Decimal(repr(variance))


def _blank_order(values: list[Decimal], blanks: list[bool], blank_first: bool) -> tuple[list[int], int, int]:
    """Positions of the values in sorted order for MEDIANX / PERCENTILEX where a BLANK result counts as zero (live Power BI, Task 79): a BLANK
    sorts among the numbers at zero, and also returns the number of BLANKs in the run of zeros when it holds a real zero too (0 otherwise) and
    the length of that run.  How a BLANK and a real zero order between themselves is not settled: the same mix on the pick gave the zero in some
    row sets (the standard Facts under Quantity <> 3, d37, d39, d45) and the BLANK in others (d38, d40, d44, d48, d50), and no order by position,
    count, size or storage fits both (blank-first, blank-last, either stable order, libstdc++ nth_element, a size limit each miss held-out sets).
    So a pick that lands in a run of zeros holding both a BLANK and a real zero is refused, for every body and size, except the one run that was
    measured the same way every time: one BLANK and one real zero (the standard Facts, d46), where the second of the two is the zero
    (_blank_unsettled).  Two picks that average are refused only when both can be BLANKs (two or more in the run); with one BLANK in the run, or
    one pick a number, the average is the same whichever order the run has.  blank_first is kept for callers and does not change the order."""
    zeros = [index for index in range(len(values)) if values[index] == 0]
    blank_run = sum(1 for index in zeros if blanks[index])
    mixed_zero = blank_run > 0 and blank_run < len(zeros)
    order = sorted(range(len(values)), key=lambda index: (values[index], not blanks[index]))
    return order, blank_run if mixed_zero else 0, len(zeros)


def _blank_unsettled(blank_run: int, run_length: int, zero: bool, picked: Decimal | None, column: bool) -> bool:
    """True when a single pick lands in a mixed run of zeros whose order is not known: any run but one BLANK with one real zero, whose second
    value (the real zero) is the measured answer over a column reference; the first, the BLANK, was not measured and is refused, and an expression
    body measured both ways (d12) is refused whole."""
    if not (blank_run and zero):
        return False
    return not (column and blank_run == 1 and run_length == 2 and picked is not None)


def _blank_read(position: int, values: list[Decimal], blanks: list[bool], order: list[int]) -> tuple[bool, Decimal | None]:
    """(the sorted value is zero, the value or None for a BLANK) at a sorted position."""
    index = order[position]
    return values[index] == 0, None if blanks[index] else values[index]


_BLANK_ZERO_REFUSAL = "MEDIANX / PERCENTILEX landing on a zero that is both a BLANK and a number is not modelled by the local engine."


def _blank_median(values: list[Decimal], blanks: list[bool], blank_first: bool) -> Decimal | None:
    """MEDIAN with BLANK results among the values (live Power BI, Task 79): the middle value is BLANK when it lands on a BLANK; the average of two
    middle values is BLANK only when both are, otherwise a BLANK counts as zero (BLANK + x is x in DAX)."""
    count = len(values)
    order, zero_mixed, run_length = _blank_order(values, blanks, blank_first)
    middle = count // 2
    if count % 2:
        zero, picked = _blank_read(middle, values, blanks, order)
        if _blank_unsettled(zero_mixed, run_length, zero, picked, blank_first):
            raise dax_typed.refusal(_BLANK_ZERO_REFUSAL)
        return picked
    low_zero, low = _blank_read(middle - 1, values, blanks, order)
    high_zero, high = _blank_read(middle, values, blanks, order)
    if zero_mixed > 1 and low_zero and high_zero:
        raise dax_typed.refusal(_BLANK_ZERO_REFUSAL)  # BLANK + BLANK is BLANK, BLANK + 0 is 0: the two picks decide it
    if low is None and high is None:
        return None
    return _interpolate(Decimal(0) if low is None else low, Decimal(0) if high is None else high, Decimal("0.5"))


def _blank_percentile(name: str, values: list[Decimal], blanks: list[bool], k: Decimal, blank_first: bool) -> Decimal | None:
    """PERCENTILEX with BLANK results among the values (live Power BI, Task 79): the same position rule as the numbers, with the BLANK rules of
    _blank_median for the two values the position falls between."""
    count = len(values)
    order, zero_mixed, run_length = _blank_order(values, blanks, blank_first)
    position = k * (count - 1) if name == "PERCENTILE.INC" else k * (count + 1) - 1
    low = int(position.to_integral_value(rounding=ROUND_FLOOR))
    fraction = position - low
    if low + 1 >= count:
        zero, picked = _blank_read(count - 1 if low >= count - 1 else low, values, blanks, order)
        if _blank_unsettled(zero_mixed, run_length, zero, picked, blank_first):
            raise dax_typed.refusal(_BLANK_ZERO_REFUSAL)
        return picked
    first_zero, first = _blank_read(low, values, blanks, order)
    if fraction == 0:
        if _blank_unsettled(zero_mixed, run_length, first_zero, first, blank_first):
            raise dax_typed.refusal(_BLANK_ZERO_REFUSAL)
        return first
    second_zero, second = _blank_read(low + 1, values, blanks, order)
    if zero_mixed > 1 and first_zero and second_zero:
        raise dax_typed.refusal(_BLANK_ZERO_REFUSAL)
    if first is None and second is None:
        return None
    return _interpolate(Decimal(0) if first is None else first, Decimal(0) if second is None else second, fraction)


def check_percentile_k(name: str, count: int, k: Decimal) -> None:
    """The k range of PERCENTILE.INC / PERCENTILE.EXC (and their X forms) over count data values; a refusal when k is out of range.
    Task 154: Power BI checks k against the rows iterated even when every value is BLANK, so the check does not depend on the values."""
    if name in {"PERCENTILE.INC", "PERCENTILEX.INC"}:
        if not Decimal(0) <= k <= Decimal(1):
            raise dax_typed.refusal("The percentile value should be in the range 0..1, inclusive.")
    elif not Decimal(1) / (count + 1) <= k <= Decimal(count) / (count + 1):
        raise dax_typed.refusal(
            "The percentile value should be in the range 1/(N+1)..N/(N+1) inclusive, where N is the number of data values."
        )


def statistic(function: str, values: list[Decimal], k: Decimal | None = None, blanks: list[bool] | None = None, blank_first: bool = False) -> Decimal | None:
    """Statistic over the non-blank numbers of a column or iterator; None when there is nothing to compute.  blanks (MEDIANX / PERCENTILEX only)
    marks the values that were BLANK results, which are zero here; blank_first says the values are a column reference (BLANK before a zero)."""
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
        if any(not value.is_finite() for value in values):
            # live Power BI (Task 39 review): a NaN factor keeps its own sign; Infinity * 0 is the negative default NaN; otherwise the sign of the product
            nans = [value for value in values if value.is_nan()]
            if nans:
                if any(value == 0 for value in values):
                    # live Power BI (Task 39 review): PRODUCTX over the rows 0 and NaN (the NaN made by 1/0-1/0 in the body) printed a POSITIVE nan, while
                    # every NaN beside non-zero factors printed -nan(ind); the sign of a NaN beside a zero factor is not settled, so it is refused
                    raise dax_typed.refusal(f"{function} with a NaN beside a zero factor: the sign of the NaN Power BI prints is not modelled by the local engine.")
                return nans[0]
            if any(value == 0 for value in values):
                return Decimal("-NaN")
            return Decimal("-Infinity") if sum(1 for value in values if value.is_signed()) % 2 else Decimal("Infinity")
        product = Decimal(1)
        for value in values:
            product *= value
        if product.is_finite() and abs(product) > Decimal("1.7976931348623157E+308"):
            return Decimal("Infinity") if product > 0 else Decimal("-Infinity")  # Part B: beyond the double range is Infinity
        return product
    if name == "MEDIAN":
        if blanks is not None and any(blanks) and all(value.is_finite() for value in values):
            return _blank_median(values, blanks, blank_first)
        nans = [value for value in values if value.is_nan()]
        if nans:
            if len(nans) == count:
                return nans[0]
            # live Power BI (Task 39 review): NaN beside other numbers gives NaN, 0 or the number by position (MEDIANX({1,2,3},IF([Value]>1,0/0,[Value])) is NaN, 6 rows 0,NaN,0,NaN,0,NaN is 0)
            raise dax_typed.refusal(f"{function} with NaN beside other numbers depends on the order the engine sorts them in, which the local engine does not model.")
        ordered = sorted(values)
        middle = count // 2
        if count % 2:
            return ordered[middle]
        answer = _interpolate(ordered[middle - 1], ordered[middle], Decimal("0.5"))
        if answer.is_finite() and any(not value.is_finite() for value in values):
            answer = Decimal(f"{float(answer):.15g}")  # a Double result beside Infinities, 15 digits as Power BI shows it
        return answer
    if name == "GEOMEAN":
        if any(value == 0 or value.is_nan() for value in values):
            return Decimal(0)  # a zero, or a NaN beside anything, gives 0 (measured)
        if any(value.is_infinite() for value in values):
            negatives = sum(1 for value in values if value < 0)
            if negatives % 2 and count % 2 == 0:
                return Decimal("NaN")  # live Power BI (Task 39 review): an even root of a negative product is NaN, printed nan (GEOMEANX({-1,2,5,0},1/[Value]) is nan)
            return Decimal("-Infinity") if negatives % 2 else Decimal("Infinity")
        negatives = sum(1 for value in values if value < 0)
        magnitude = _double(math.exp(sum(math.log(abs(float(value))) for value in values) / count), function)
        if negatives % 2 and count % 2 == 0:
            return Decimal("NaN")  # live Power BI (Task 72 review): an even root of a negative product is NaN, as in the Infinity branch above
        # live Power BI (Task 11 review): the geometric mean of the absolute values, negative when the product is (an odd number of negative values)
        return -magnitude if negatives % 2 else magnitude
    if name in {"VAR.S", "VAR.P", "STDEV.S", "STDEV.P"}:
        sample = name.endswith(".S")
        if sample and count < 2:
            error = dax_typed._error(f"Division by zero has occurred when evaluating function '{function}'.")
            error.sample_statistic_nan = True  # NaN in Power BI (iteration 88); see the measure-level handling in measures.resolve
            raise error
        if any(not value.is_finite() for value in values):
            nan_count = sum(1 for value in values if value.is_nan())
            if sample and 0 < nan_count < count and not (nan_count == 1 and all(value.is_infinite() for value in values if not value.is_nan())):
                # live Power BI (Task 39 review): VARX.S of NaN beside other numbers is 0 for [1,NaN,NaN] and NaN for [NaN,1,NaN]: only one NaN beside
                # nothing but Infinities (8 measured, 0 each) is settled
                raise dax_typed.refusal(f"{function} with NaN beside other numbers is not modelled by the local engine.")
            return Decimal(0)
        if count > 1 and len(set(values)) == 1 and values[0] != values[0].to_integral_value():
            # live Power BI (Task 11 review): the spread of one repeated fraction is float noise (8.4E-08), not 0
            # Task 47 Part B: the noise is the double arithmetic of the rows (double_statistic), not a refusal
            return double_statistic(name, values)  # name is already the VAR.S / STDEV.P form here
        mean = sum(values, Decimal(0)) / count
        variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / (count - 1 if sample else count)
        answer = variance if name.startswith("VAR") else variance.sqrt()
        if function in {"VARX.P", "VARX.S", "STDEVX.P", "STDEVX.S"}:
            # Task 144 family M (measured): the iterator forms are Power BI doubles; the double answer replaces the exact one only where they differ at 15 digits
            double_answer = double_statistic(name, values)
            if double_answer.is_finite() and Context(prec=15).plus(double_answer) != Context(prec=15).plus(answer):
                return double_answer
        return answer
    if name in {"PERCENTILE.INC", "PERCENTILE.EXC"}:
        # Task 144 family J (measured): a percentile outside its range, or a BLANK one for EXC, fails the whole query: IFERROR cannot catch it,
        # so it is a refusal (a MeasureError), not a MeasureRuntimeError that IFERROR would turn into its fallback
        if k is None:
            if name == "PERCENTILE.EXC":
                raise dax_typed.refusal("PERCENTILE.EXC with a BLANK percentile fails the query; the local engine does not return its IFERROR fallback.")
            raise _fail(function)
        check_percentile_k(name, count, k)
        nans = [value for value in values if value.is_nan()]
        if nans:
            if len(nans) == count:
                return nans[0]
            raise dax_typed.refusal(f"{function} with NaN beside other numbers depends on the order the engine sorts them in, which the local engine does not model.")
        if blanks is not None and any(blanks) and all(value.is_finite() for value in values):
            return _blank_percentile(name, values, blanks, k, blank_first)
        ordered = sorted(values)
        position = k * (count - 1) if name == "PERCENTILE.INC" else k * (count + 1) - 1
        low = int(position.to_integral_value(rounding=ROUND_FLOOR))
        fraction = position - low
        if low + 1 >= count:
            return ordered[-1] if low >= count - 1 else ordered[low]
        answer = _interpolate(ordered[low], ordered[low + 1], fraction)
        if answer.is_finite() and any(not value.is_finite() for value in values):
            answer = Decimal(f"{float(answer):.15g}")
        return answer
    raise _fail(function)
