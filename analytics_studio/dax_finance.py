"""DAX financial functions, matching Power BI Desktop 2.157.879.0 (see analytics_studio/dax_ext.py for the module contract).

Every rule below was read from the live engine (``tools/dax_battery_finance.json`` holds the saved battery):

* arguments are converted in order (text numbers are accepted, TRUE is 1, BLANK is 0); a bad text argument raises
  ``Cannot convert value 'x' of type Text to type Number`` or, for the whole-number arguments (``type``, ``month``, the
  DB / DDB period, the CUMIPMT / CUMPRINC periods, NPERY, the DOLLARDE / DOLLARFR fraction), ``... to type Integer``;
  a whole-number argument rounds half away from zero and must fit in 64 bits;
* PMT, PV, FV, NPER, IPMT, PPMT and ISPMT return BLANK when their third argument (the fourth for IPMT, PPMT and ISPMT)
  is BLANK and the next optional argument is BLANK or omitted, but only when no error is raised first;
* PV, FV and RATE use the textbook formulas in double precision with the engine's own power (whole exponents by
  repeated squaring), so PV(1E-8, 360, -1000) is exactly as inexact as in Power BI; PMT, IPMT, PPMT, CUMIPMT and
  CUMPRINC are evaluated with expm1 / log1p and stay accurate for tiny rates and huge periods;
* RATE is Power BI's secant iteration (second point 0.001 below the guess when the residual there is positive, above
  it otherwise; 200 iterations; done when the step and the residual are both below 1E-7; an unfinished run is accepted
  when the residual is below 1E-4), reproduced including the cases where it gives up;
* VDB counts its periods from the fractional part of the start period and DB / DDB round their period; the
  declining balance / straight line switch follows the same book-value rules as DDB and SLN.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext
import math

from analytics_studio import dax_typed

ARITY: dict[str, tuple[int, int]] = {
    "PMT": (3, 5), "PV": (3, 5), "FV": (3, 5), "NPER": (3, 5), "RATE": (3, 6), "IPMT": (4, 6), "PPMT": (4, 6),
    "CUMIPMT": (6, 6), "CUMPRINC": (6, 6), "ISPMT": (4, 4), "SLN": (3, 3), "SYD": (4, 4), "DB": (4, 5), "DDB": (4, 5),
    "VDB": (5, 7), "EFFECT": (2, 2), "NOMINAL": (2, 2), "RRI": (3, 3), "PDURATION": (3, 3), "DOLLARDE": (2, 2),
    "DOLLARFR": (2, 2),
}
CATEGORY: dict[str, str] = {}

_GENERIC = "An argument of function '{}' has the wrong data type or the result is too large or too small."
_INVALID = "An argument of function '{}' has the wrong data type or has an invalid value."
_ZERO_DIVISION = "Division by zero has occurred when evaluating function '{}'."


def _fail(function: str) -> Exception:
    return dax_typed._error(_GENERIC.format(function))


def _division(function: str) -> Exception:
    return dax_typed._error(_ZERO_DIVISION.format(function))


def _number(value: object, function: str) -> float:
    """A Number argument as a double: blank is 0, TRUE is 1, text numbers convert, anything else is an error."""
    number = dax_typed.to_number(value)
    if not isinstance(number, Decimal) or not number.is_finite():
        raise _fail(function)
    result = float(number)
    if math.isinf(result):
        raise _fail(function)
    return result


_CONVERSION = "The result of a conversion or arithmetic operation is either too large or too small."


def _integer(value: object, function: str) -> int:
    """An Integer argument: text must be a number, then the value rounds half away from zero (64-bit range)."""
    if isinstance(value, str):
        try:
            number = dax_typed.text_to_number(value)
        except Exception as exc:  # the engine words this one for the Integer type
            raise dax_typed._error(f"Cannot convert value '{value}' of type Text to type Integer.") from exc
    else:
        number = dax_typed.to_number(value)
    if not number.is_finite():
        raise _fail(function)
    if abs(number) >= Decimal(2) ** 63:
        raise dax_typed._error(_CONVERSION)
    return int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _result(value: float, function: str) -> Decimal:
    if math.isnan(value) or math.isinf(value):
        raise _fail(function)
    return Decimal(repr(value)) if value != 0 else Decimal(0)


def _power(base: float, exponent: float) -> float:
    """base ** exponent the way the engine evaluates it: whole exponents by repeated squaring (this is what makes
    PV(1E-8, 360, -1000) come out as Power BI's 359999.346407639), other exponents with the C library pow."""
    if exponent == math.floor(exponent) and abs(exponent) < 4294967295:
        count = int(abs(exponent))
        result = 1.0
        factor = base
        try:
            while count:
                if count & 1:
                    result *= factor
                factor *= factor
                count >>= 1
        except OverflowError:
            return math.inf
        if exponent < 0:
            return _div(1.0, result)
        return result
    if base > 0:
        try:
            return _root(base, exponent)
        except OverflowError:
            return math.inf
    return math.pow(base, exponent)


def _pow(base: float, exponent: float, function: str) -> float:
    """_power() with the engine's error rules: 0^0 and a negative base with a fractional exponent are plain errors,
    0 raised to a negative power is a division by zero, overflow gives infinity."""
    if base == 0:
        if exponent == 0:
            raise _fail(function)
        if exponent < 0:
            raise _division(function)
        return 0.0
    try:
        return _power(base, exponent)
    except OverflowError:
        return math.inf
    except ValueError as exc:
        raise _fail(function) from exc


_TINY_LOG = 2.0 ** -55


def _root(base: float, exponent: float) -> float:
    """``base ** exponent`` for a fractional exponent as Power BI's NOMINAL and RRI evaluate it.

    The engine's power function is not correctly rounded.  A result above 1 is cut down to the double below the exact
    value (unless the exact value is within 0.1 of the next double, which it then reaches); when the exponent times
    ln(base) is smaller than 2^-55 it answers one step on the other side of 1 (0.99999999999999989 for growth,
    1.0000000000000002 for decay) instead of 1.  All of this is invisible in one result but not once it is multiplied by
    a huge number of periods (NOMINAL(0.05, 1E18) is -111.02, not 0.04879)."""
    if base <= 0:
        return math.pow(base, exponent)
    log = exponent * math.log(base)
    if log != 0 and abs(log) < _TINY_LOG:
        return 1.0 - 2.0 ** -53 if log > 0 else 1.0 + 2.0 ** -52
    try:
        with localcontext() as context:
            context.prec = 60
            exact = Decimal(base) ** Decimal(exponent)
            value = float(exact)
            if math.isinf(value):
                raise OverflowError("power overflow")
            if log > 0:
                if Decimal(value) > exact:
                    value = math.nextafter(value, 0.0)
                step = math.nextafter(value, math.inf) - value
                if (exact - Decimal(value)) >= Decimal(step) * Decimal("0.9"):
                    value = math.nextafter(value, math.inf)
    except ArithmeticError:
        return math.pow(base, exponent)
    return value


def _blank_tail(args: list[object], position: int) -> bool:
    """True when ``args[position]`` is BLANK and the next optional argument is BLANK or missing."""
    return args[position] is None and (len(args) <= position + 1 or args[position + 1] is None)


def _paid_type(args: list[object], position: int, function: str) -> int:
    if len(args) <= position:
        return 0
    return 1 if _integer(args[position], function) != 0 else 0


# ------------------------------------------------------------------------------------------ annuities


def _payment(rate: float, nper: float, pv: float, fv: float, kind: int, function: str) -> float:
    """PMT, evaluated through expm1 / log1p so tiny rates and huge periods stay accurate."""
    if nper == 0 or rate <= -1:
        raise _fail(function)
    if rate == 0:
        return -(pv + fv) / nper
    exponent = -nper * math.log1p(rate)
    discount = _exp(exponent)
    if math.isinf(discount):
        return math.nan
    return _div(-rate * (pv + fv * discount), -_expm1(exponent)) / (1 + rate * kind)


def _exp(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _expm1(value: float) -> float:
    try:
        return math.expm1(value)
    except OverflowError:
        return math.inf


def _div(numerator: float, denominator: float) -> float:
    """Float division that gives infinity / NaN like IEEE doubles instead of raising."""
    if denominator == 0:
        if numerator == 0 or math.isnan(numerator):
            return math.nan
        return math.copysign(math.inf, numerator) * math.copysign(1.0, denominator)
    return numerator / denominator


def _pmt(args: list[object]) -> object:
    f = "PMT"
    rate, nper, pv = (_number(args[i], f) for i in range(3))
    fv = _number(args[3], f) if len(args) > 3 else 0.0
    kind = _paid_type(args, 4, f)
    payment = _payment(rate, nper, pv, fv, kind, f)
    if _blank_tail(args, 2):
        return None
    return _result(payment, f)


def _pv(args: list[object]) -> object:
    f = "PV"
    rate, nper, pmt = (_number(args[i], f) for i in range(3))
    fv = _number(args[3], f) if len(args) > 3 else 0.0
    kind = _paid_type(args, 4, f)
    if rate == 0:
        value = -(fv + pmt * nper)
    else:
        growth = _pow(1 + rate, nper, f)
        if growth == 0:
            raise _division(f)
        value = -(fv + pmt * (1 + rate * kind) * (growth - 1) / rate) / growth
    if _blank_tail(args, 2):
        return None
    return _result(value, f)


def _fv(args: list[object]) -> object:
    f = "FV"
    rate, nper, pmt = (_number(args[i], f) for i in range(3))
    pv = _number(args[3], f) if len(args) > 3 else 0.0
    kind = _paid_type(args, 4, f)
    if rate == 0:
        value = -(pv + pmt * nper)
    else:
        growth = _pow(1 + rate, nper, f)
        value = -(pv * growth + pmt * (1 + rate * kind) * (growth - 1) / rate)
    if _blank_tail(args, 2):
        return None
    return _result(value, f)


def _nper(args: list[object]) -> object:
    f = "NPER"
    rate, pmt, pv = (_number(args[i], f) for i in range(3))
    fv = _number(args[3], f) if len(args) > 3 else 0.0
    kind = _paid_type(args, 4, f)
    if rate == 0:
        if pmt == 0:
            raise _division(f)
        value = -(pv + fv) / pmt
    else:
        adjusted = pmt * (1 + rate * kind)
        ratio = _div(adjusted - fv * rate, adjusted + pv * rate)
        if math.isnan(ratio) or ratio <= 0 or math.isinf(ratio) or 1 + rate <= 0:
            raise _fail(f)
        growth = math.log(1 + rate)
        if growth == 0:
            raise _division(f)
        value = math.log(ratio) / growth
    if _blank_tail(args, 2):
        return None
    return _result(value, f)


# ------------------------------------------------------------------------------------------ RATE

_RATE_STEP = 0.001
_RATE_TOLERANCE = 1e-7
_RATE_ITERATIONS = 200
_RATE_GIVE_UP = 1e-4
_RATE_FLOOR = -1 + 1e-7


def _rate_residual(rate: float, nper: float, pmt: float, pv: float, fv: float, kind: int) -> float:
    if rate == 0:
        return pv + pmt * nper + fv
    growth = _power(1 + rate, nper)
    return pv * growth + pmt * ((1 + rate * kind) * (growth - 1) / rate) + fv


def _rate(args: list[object]) -> object:
    f = "RATE"
    nper, pmt, pv = (_number(args[i], f) for i in range(3))
    fv = _number(args[3], f) if len(args) > 3 else 0.0
    kind = _paid_type(args, 4, f)
    guess = _number(args[5], f) if len(args) > 5 else 0.1
    if guess <= -1:
        raise dax_typed._error(_INVALID.format(f))
    if nper <= 0:
        raise _fail(f)
    try:
        value = _rate_search(nper, pmt, pv, fv, kind, guess)
    except (OverflowError, ZeroDivisionError, ValueError):
        value = None
    if value is None:
        raise _fail(f)
    return _result(value, f)


def _rate_search(nper: float, pmt: float, pv: float, fv: float, kind: int, guess: float) -> float | None:
    def residual(rate: float) -> float:
        return _rate_residual(rate, nper, pmt, pv, fv, kind)

    x0 = guess
    y0 = residual(x0)
    x1 = guess - _RATE_STEP if y0 > 0 else guess + _RATE_STEP
    y1 = residual(x1)
    for _ in range(_RATE_ITERATIONS):
        if y1 == y0:
            return None
        x2 = x1 - (x1 - x0) * y1 / (y1 - y0)
        if math.isnan(x2) or math.isinf(x2) or x2 <= -1:
            return None
        if abs(x2 - x1) < _RATE_TOLERANCE and abs(residual(x2)) < _RATE_TOLERANCE:
            return x2 if x2 > _RATE_FLOOR else None
        x0, y0, x1 = x1, y1, x2
        y1 = residual(x1)
    if abs(y1) < _RATE_GIVE_UP and x1 > _RATE_FLOOR:
        return x1
    return None


# ------------------------------------------------------------------------------------------ interest and principal


def _balance(rate_log: float, nper: float, pv: float, fv: float, elapsed: float) -> float:
    """Loan balance after ``elapsed`` periods (the textbook ``pv * (1+r)^j + pmt * ((1+r)^j - 1) / r`` with the
    level payment folded in), written with growth factors relative to ``nper`` so it never overflows."""
    after = _exp((elapsed - nper) * rate_log)
    numerator = -pv * _expm1((elapsed - nper) * rate_log) + (fv * after * _expm1(-elapsed * rate_log) if fv else 0.0)
    return _div(numerator, -_expm1(-nper * rate_log))


def _interest(rate: float, per: float, nper: float, pv: float, fv: float, kind: int, function: str) -> tuple[float, float]:
    """(interest, payment) of period ``per``; the caller has checked 1 <= per < nper + 1."""
    payment = _payment(rate, nper, pv, fv, kind, function)
    if rate == 0:
        return 0.0, payment
    rate_log = math.log1p(rate)
    if kind == 0:
        return -rate * _balance(rate_log, nper, pv, fv, per - 1), payment
    if per == 1:
        return 0.0, payment
    return (-_balance(rate_log, nper, pv, fv, per - 2) - payment) * rate, payment


def _period_payment(args: list[object], function: str) -> tuple[float, float]:
    rate, per, nper, pv = (_number(args[i], function) for i in range(4))
    fv = _number(args[4], function) if len(args) > 4 else 0.0
    kind = _paid_type(args, 5, function)
    if rate <= -1 or nper <= 0 or per < 1 or per >= nper + 1:
        raise _fail(function)
    interest, payment = _interest(rate, per, nper, pv, fv, kind, function)
    return interest, payment


def _ipmt(args: list[object]) -> object:
    f = "IPMT"
    interest, _ = _period_payment(args, f)
    if _blank_tail(args, 3):
        return None
    return _result(interest, f)


def _ppmt(args: list[object]) -> object:
    f = "PPMT"
    interest, payment = _period_payment(args, f)
    if _blank_tail(args, 3):
        return None
    return _result(payment - interest, f)


def _cumulative(function: str, args: list[object]) -> object:
    """CUMIPMT / CUMPRINC: the sum of IPMT / PPMT over the rounded start..end periods, in closed form.

    With B(j) the balance after j payments (``pv * (1 - g^(j-nper)) / (1 - g^-nper)`` for growth g = 1 + rate and no
    future value) the interest of period k is ``-rate * B(k-1)`` (type 0) or ``-rate * B(k-2) - payment * rate / g``
    (type 1, k >= 2, none in period 1); the principal of period k is the drop of the balance, so CUMPRINC telescopes.
    """
    rate, nper, pv = (_number(args[i], function) for i in range(3))
    first, last = _integer(args[3], function), _integer(args[4], function)
    kind = _integer(args[5], function)
    if rate <= 0 or nper <= 0 or pv <= 0 or first < 1 or last < first or last > nper or kind not in (0, 1):
        raise _fail(function)
    rate_log = math.log1p(rate)
    shortfall = -_expm1(-nper * rate_log)
    payment = _div(-rate * pv, shortfall)  # level payment of a type-0 loan with no future value
    low = first if kind == 0 else max(first, 2)
    count = last - low + 1
    lag = 1 if kind == 0 else 2
    # growth^(j-nper) summed over j = low-lag .. last-lag, written from the largest term down so it never overflows
    top = _exp((last - lag - nper) * rate_log)
    span = -_expm1(-count * rate_log) if count > 0 else 0.0
    if function == "CUMIPMT":
        if count <= 0:
            return _result(0.0, function)
        growth_sum = top * span / -_expm1(-rate_log)
        interest = -rate * _div(pv * (count - growth_sum), shortfall)
        if kind == 1:
            interest -= count * payment * rate / (1 + rate)
        return _result(interest, function)
    principal_top = _exp((last - kind - nper) * rate_log)  # growth^(last-nper) for type 0, growth^(last-1-nper) for type 1
    principal = -pv * _div(principal_top * span, shortfall) if count > 0 else 0.0
    if kind == 1 and first == 1:
        principal += payment / (1 + rate)
    return _result(principal, function)


def _ispmt(args: list[object]) -> object:
    f = "ISPMT"
    rate, per, nper, pv = (_number(args[i], f) for i in range(4))
    if nper == 0:
        raise _division(f)
    value = pv * rate * (per / nper - 1)
    if args[3] is None:
        return None
    return _result(value, f)


# ------------------------------------------------------------------------------------------ depreciation


def _sln(args: list[object]) -> object:
    f = "SLN"
    cost, salvage, life = (_number(args[i], f) for i in range(3))
    if life == 0:
        raise _division(f)
    return _result((cost - salvage) / life, f)


def _syd(args: list[object]) -> object:
    f = "SYD"
    cost, salvage, life, per = (_number(args[i], f) for i in range(4))
    if life <= 0 or salvage < 0 or per <= 0 or per > life:
        raise _fail(f)
    denominator = life * (life + 1)
    if math.isinf(denominator):
        raise _division(f)
    return _result((cost - salvage) * (life - per + 1) * 2 / denominator, f)


def _db(args: list[object]) -> object:
    f = "DB"
    cost, salvage, life = (_number(args[i], f) for i in range(3))
    whole_period = _integer(args[3], f)
    month = _integer(args[4], f) if len(args) > 4 else 12
    if cost < 0 or salvage < 0 or life <= 0 or not 1 <= month <= 12:
        raise _fail(f)
    if whole_period < 1 or whole_period > (life if month == 12 else life + 1):
        raise _fail(f)
    if life >= 2**31 and whole_period < 2**31:
        raise _fail(f)  # the engine cannot walk a life beyond the 32-bit range with a small period
    if cost == 0:
        return Decimal(0)
    try:
        raw_rate = 1 - math.pow(salvage / cost, 1 / life)
    except OverflowError as exc:
        raise _fail(f) from exc
    if math.isinf(raw_rate) or math.isnan(raw_rate):
        raise _fail(f)
    rate = float(Decimal(repr(raw_rate)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    first = cost * rate * month / 12
    if whole_period == 1 and whole_period <= life:
        return _result(first, f)
    # book value after the first period is cost - first and shrinks by (1 - rate) every later period
    elapsed = max(whole_period - 1, 1)
    remaining = (cost - first) * math.pow(1 - rate, elapsed - 1)
    if whole_period <= life:
        return _result(remaining * rate, f)
    return _result(remaining * rate * (12 - month) / 12, f)


def _ddb_value(cost: float, salvage: float, life: float, period: int, factor: float) -> float:
    rate = factor / life
    if rate >= 1:
        old = cost if period == 1 else 0.0
        new = 0.0
    else:
        old = cost * math.pow(1 - rate, period - 1)
        new = cost * math.pow(1 - rate, period)
    value = old - salvage if new < salvage else old - new
    return max(value, 0.0)


def _ddb(args: list[object]) -> object:
    f = "DDB"
    cost, salvage, life = (_number(args[i], f) for i in range(3))
    whole_period = _integer(args[3], f)
    factor = _number(args[4], f) if len(args) > 4 else 2.0
    if cost < 0 or salvage < 0 or life <= 0 or factor <= 0:
        raise _fail(f)
    if whole_period < 1 or whole_period > life:
        raise _fail(f)
    return _result(_ddb_value(cost, salvage, life, whole_period, factor), f)


_VDB_STEP_LIMIT = 20_000_000


def _vdb_plain(cost: float, salvage: float, life: float, start: float, end: float, factor: float) -> float:
    """No-switch VDB: the whole periods' declining balance, the first and last one scaled to the part inside the span."""
    first_whole, last_whole = math.floor(start), math.ceil(end)
    if last_whole - first_whole > _VDB_STEP_LIMIT:
        raise _fail("VDB")
    total = 0.0
    for index in range(first_whole + 1, last_whole + 1):
        term = _ddb_value(cost, salvage, life, index, factor)
        if index == first_whole + 1:
            term *= min(end, first_whole + 1.0) - start
        elif index == last_whole:
            term *= end + 1.0 - last_whole
        total += term
    return total


def _vdb_switching(cost: float, salvage: float, life: float, start: float, end: float, factor: float) -> float:
    """VDB with the switch to straight line.  Periods are counted from the fractional part of ``start`` (so ``start`` is
    a period boundary): a first part of that length, then whole periods; every period takes the declining balance, or,
    from the first period whose straight-line amount is larger, the straight-line amount (book value minus salvage over
    the life that is left) for the rest of the life.  A declining balance held at the salvage floor never switches
    when ``start`` is fractional."""
    phase = start - math.floor(start)
    if phase < 1e-12:
        phase = 0.0
    rate = min(factor / life, 1.0)
    book = cost
    total = 0.0
    boundary = 0.0
    following = phase if phase > 0 else 1.0
    steps = 0
    while boundary < end:
        steps += 1
        if steps > _VDB_STEP_LIMIT:
            raise _fail("VDB")
        floor_gap = book - salvage
        if abs(floor_gap) <= 1e-12 * max(1.0, abs(cost), abs(salvage)):
            break  # the book value sits at the salvage value: nothing is left to depreciate
        decline = min(book * rate, floor_gap)
        if boundary == 0.0 and phase > 0:
            decline = max(decline, 0.0)  # the part before ``start`` never writes a book value up to a higher salvage value
        straight = floor_gap / (life - boundary)
        capped = book * rate > floor_gap
        low = max(boundary, start)
        if straight > decline and book > salvage and not (capped and phase > 0):
            return total + straight * (end - low)
        high = min(following, end)
        if high > low:
            total += decline * (high - low)
        book -= decline * (following - boundary)
        boundary, following = following, following + 1.0
    return total


def _vdb(args: list[object]) -> object:
    f = "VDB"
    cost, salvage, life, start, end = (_number(args[i], f) for i in range(5))
    factor = _number(args[5], f) if len(args) > 5 else 2.0
    no_switch = _truth(args[6]) if len(args) > 6 else False
    if start < 0 or end < start or end > life or cost < 0 or salvage < 0 or factor < 0 or life <= 0:
        raise _fail(f)
    if no_switch:
        return _result(_vdb_plain(cost, salvage, life, start, end, factor), f)
    return _result(_vdb_switching(cost, salvage, life, start, end, factor), f)


def _truth(value: object) -> bool:
    """A True/False argument: numbers are true when non-zero, the text TRUE / FALSE and number text convert, blank
    text is false."""
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return False
        if text.upper() in {"TRUE", "FALSE"}:
            return text.upper() == "TRUE"
        try:
            return dax_typed.text_to_number(text) != 0
        except Exception as exc:
            raise dax_typed._error(f"Cannot convert value '{value}' of type Text to type True/False.") from exc
    return dax_typed.to_boolean(value)


# ------------------------------------------------------------------------------------------ rates and prices


def _effect(args: list[object]) -> object:
    f = "EFFECT"
    nominal = _number(args[0], f)
    periods = _integer(args[1], f)
    if nominal <= 0 or periods < 1:
        raise _fail(f)
    return _result(_power(1 + nominal / periods, float(periods)) - 1, f)


def _nominal(args: list[object]) -> object:
    f = "NOMINAL"
    effective = _number(args[0], f)
    periods = _integer(args[1], f)
    if effective <= 0 or periods < 1:
        raise _fail(f)
    try:
        root = _root(1 + effective, 1 / periods)
    except OverflowError as exc:
        raise _fail(f) from exc
    return _result(periods * (root - 1), f)


def _rri(args: list[object]) -> object:
    f = "RRI"
    nper, pv, fv = (_number(args[i], f) for i in range(3))
    if nper <= 0:
        raise _fail(f)
    if pv == 0:
        if fv == 0:
            return Decimal(0)
        raise _fail(f)
    ratio = _div(fv, pv)
    if ratio < 0 or math.isinf(ratio):
        raise _fail(f)
    try:
        value = _root(ratio, 1 / nper) - 1
    except OverflowError as exc:
        raise _fail(f) from exc
    return _result(value, f)


def _pduration(args: list[object]) -> object:
    f = "PDURATION"
    rate, pv, fv = (_number(args[i], f) for i in range(3))
    if rate <= 0 or pv <= 0 or fv <= 0:
        raise _fail(f)
    growth = math.log(1 + rate)
    if growth == 0:
        raise _division(f)
    return _result((math.log(fv) - math.log(pv)) / growth, f)


def _dollar(function: str, args: list[object]) -> object:
    price = _number(args[0], function)
    fraction = _integer(args[1], function)
    if fraction == 0:
        raise _division(function)
    if fraction < 0:
        raise _fail(function)
    if args[0] is None:
        return None
    digits = 0 if fraction == 1 else len(str(fraction - 1))
    scale = float(10 ** digits)
    whole = float(math.trunc(price))
    part = price - whole
    if function == "DOLLARDE":
        return _result(whole + part * scale / fraction, function)
    return _result(whole + part * fraction / scale, function)


def call(function: str, args: list[object]) -> object:
    if function in {"CUMIPMT", "CUMPRINC"}:
        return _cumulative(function, args)
    if function in {"DOLLARDE", "DOLLARFR"}:
        return _dollar(function, args)
    return _HANDLERS[function](args)


_HANDLERS = {
    "PMT": _pmt, "PV": _pv, "FV": _fv, "NPER": _nper, "RATE": _rate, "IPMT": _ipmt, "PPMT": _ppmt, "ISPMT": _ispmt,
    "SLN": _sln, "SYD": _syd, "DB": _db, "DDB": _ddb, "VDB": _vdb, "EFFECT": _effect, "NOMINAL": _nominal,
    "RRI": _rri, "PDURATION": _pduration,
}
