"""DAX statistical distribution functions, matching Power BI Desktop 2.157.879.0 (see analytics_studio/dax_ext.py).

NORM.*, T.*, CHISQ.*, BETA.*, EXPON.DIST, POISSON.DIST and CONFIDENCE.*.  Every argument rule below (blank handling, the
rounding of "integer" arguments, the ranges Power BI rejects) was read from the live engine through
``tools/dax_battery_stats.json``.  The numerics are standard double-precision algorithms (incomplete gamma and beta
functions, Gauss-Legendre for huge parameters, AS241 for the normal quantile) accurate to well below the 1e-9 comparison
tolerance.

Known, documented differences (extreme corners where Power BI's own solver fails or approximates, see the report of
``tools/dax_battery_stats.json``): ``CHISQ.INV.RT`` for a right tail below about 1e-16 with a small number of degrees
of freedom (Power BI raises an overflow error).
"""

from __future__ import annotations

from decimal import Decimal
import math
import sys

from analytics_studio import dax_typed

ARITY: dict[str, tuple[int, int]] = {
    "NORM.DIST": (4, 4), "NORM.INV": (3, 3), "NORM.S.DIST": (2, 2), "NORM.S.INV": (1, 1),
    "T.DIST": (3, 3), "T.DIST.2T": (2, 2), "T.DIST.RT": (2, 2), "T.INV": (2, 2), "T.INV.2T": (2, 2),
    "CHISQ.DIST": (3, 3), "CHISQ.DIST.RT": (2, 2), "CHISQ.INV": (2, 2), "CHISQ.INV.RT": (2, 2),
    "BETA.DIST": (4, 6), "BETA.INV": (3, 5), "EXPON.DIST": (3, 3), "POISSON.DIST": (3, 3),
    "CONFIDENCE.NORM": (3, 3), "CONFIDENCE.T": (3, 3),
}
CATEGORY: dict[str, str] = {}

# ------------------------------------------------------------------------------------------ errors

_WRONG = "An argument of function '{}' has the wrong data type or the result is too large or too small."
_OVERFLOW = "The result of function '{}' is too large (overflow)."
_CONVERSION = "The result of a conversion or arithmetic operation is either too large or too small."
_DIVIDE = "Division by zero has occurred when evaluating function '{}'."


def _wrong(function: str) -> Exception:
    return dax_typed._error(_WRONG.format(function))


def _overflow(function: str) -> Exception:
    return dax_typed._error(_OVERFLOW.format(function))


def _divide(function: str) -> Exception:
    return dax_typed._error(_DIVIDE.format(function))


def _conversion() -> Exception:
    return dax_typed._error(_CONVERSION)


# ------------------------------------------------------------------------------------------ argument coercion

_INT64 = 9223372036854775808.0
_SQRT_MAX = math.sqrt(sys.float_info.max)
_DBL_MIN = sys.float_info.min
_TWO_PI = 2.0 * math.pi
_SQRT_TWO_PI = math.sqrt(_TWO_PI)


def _number(value: object, function: str) -> float:
    """A finite double from any DAX value (blank 0, True 1, numeric text); infinity and NaN are rejected."""
    number = dax_typed.to_number(value)
    result = float(number) if number.is_finite() else math.nan
    if math.isnan(result) or math.isinf(result):
        raise _wrong(function)
    return result


def _flag(value: object) -> bool:
    """The cumulative TRUE/FALSE argument: numbers are non-zero tests, "TRUE"/"FALSE" and numeric text are accepted."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        key = value.upper()
        if key == "TRUE":
            return True
        if key == "FALSE" or value == "":
            return False
        try:
            return dax_typed.text_to_number(value) != 0
        except Exception:
            raise dax_typed._error(f"Cannot convert value '{value.strip()}' of type Text to type True/False.") from None
    return value != 0  # type: ignore[operator]


def _round_away(value: float) -> float:
    whole = math.floor(abs(value))
    if abs(value) - whole >= 0.5:
        whole += 1.0
    return math.copysign(whole, value)


def _integer(value: object, function: str) -> int:
    """An "integer" argument: rounded half away from zero; beyond 64 bits is a conversion error."""
    number = dax_typed.to_number(value)
    if not number.is_finite():
        raise _wrong(function)
    rounded = _round_away(float(number))
    if abs(rounded) >= _INT64:
        raise _conversion()
    return int(rounded)


def _result(value: float, function: str) -> Decimal:
    if math.isnan(value) or math.isinf(value):
        raise _wrong(function)
    if value == 0:
        return Decimal(0)
    if abs(value) < _DBL_MIN:
        return Decimal(0)  # the engine flushes subnormal results
    if value == int(value) and abs(value) < 1e15:
        return Decimal(int(value))
    return Decimal(repr(value))


# ------------------------------------------------------------------------------------------ special functions

def _stirling(x: float) -> float:
    """lgamma(x) - ((x - 1/2) ln x - x + ln(2 pi) / 2) for x >= 20."""
    inverse = 1.0 / x
    square = inverse * inverse
    return inverse * (1.0 / 12 - square * (1.0 / 360 - square * (1.0 / 1260 - square * (1.0 / 1680 - square / 1188.0))))


def _log1pmx(u: float) -> float:
    """log(1 + u) - u without cancellation."""
    if abs(u) < 0.1:
        total, power = 0.0, u
        for k in range(2, 40):
            power *= -u
            term = power / k
            total += term
            if abs(term) < 1e-20 * abs(total):
                break
        return total
    if u <= -1.0:
        return -math.inf
    return math.log1p(u) - u


def _lgamma(x: float) -> float:
    return math.lgamma(x)


def _lgamma_half_step(z: float) -> float:
    """lgamma(z + 1/2) - lgamma(z) for z > 0."""
    if z < 20:
        return math.lgamma(z + 0.5) - math.lgamma(z)
    return z * _log1pmx(0.5 / z) + 0.5 * math.log(z) + _stirling(z + 0.5) - _stirling(z)


def _lbeta(a: float, b: float) -> float:
    """ln B(a, b) without cancellation for large arguments."""
    if a > b:
        a, b = b, a
    if a >= 20:
        total = a + b
        corr = _stirling(a) + _stirling(b) - _stirling(total)
        return (0.5 * math.log(_TWO_PI) - (a - 0.5) * math.log1p(b / a) - (b - 0.5) * math.log1p(a / b)
                - 0.5 * math.log(total) + corr)
    if b >= 20:
        # lgamma(b) - lgamma(a + b) for the large b
        correction = _stirling(b) - _stirling(a + b)
        diff = -(b - 0.5) * math.log1p(a / b) - a * math.log(a + b) + a + correction
        return math.lgamma(a) + diff
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _gauss_legendre(count: int) -> tuple[list[float], list[float]]:
    nodes, weights = [], []
    for i in range(count):
        x = math.cos(math.pi * (i + 0.75) / (count + 0.5))
        for _ in range(100):
            p1, p2 = 1.0, 0.0
            for j in range(count):
                p3, p2 = p2, p1
                p1 = ((2 * j + 1) * x * p2 - j * p3) / (j + 1)
            derivative = count * (x * p1 - p2) / (x * x - 1.0)
            step = p1 / derivative
            x -= step
            if abs(step) < 1e-16:
                break
        nodes.append(x)
        weights.append(2.0 / ((1.0 - x * x) * derivative * derivative))
    return nodes, weights


_GL_NODES, _GL_WEIGHTS = _gauss_legendre(18)
_GL_X = [0.5 * (1.0 + node) for node in _GL_NODES]
_GL_W = [0.5 * weight for weight in _GL_WEIGHTS]


def _gl_integral(function, low: float, high: float, width: float) -> float:
    """Composite 18-point Gauss-Legendre integral of ``function`` over [low, high] (signed), panels of at most ``width``."""
    span = high - low
    panels = max(1, math.ceil(abs(span) / width))
    half = span / (2.0 * panels)
    total = 0.0
    for panel in range(panels):
        middle = low + half * (2 * panel + 1)
        for node, weight in zip(_GL_NODES, _GL_WEIGHTS):
            total += weight * function(middle + half * node)
    return total * half


# ---- normal

def _norm_cdf(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / _SQRT_TWO_PI if abs(z) < 39 else 0.0


def _norm_inv(p: float) -> float:
    """Wichura's AS241 (PPND16), relative accuracy about 1e-16; 0 < p < 1."""
    q = p - 0.5
    if abs(q) <= 0.425:
        r = 0.180625 - q * q
        numerator = (((((((2509.0809287301226727 * r + 33430.575583588128105) * r + 67265.770927008700853) * r
                         + 45921.953931549871457) * r + 13731.693765509461125) * r + 1971.5909503065514427) * r
                      + 133.14166789178437745) * r + 3.387132872796366608)
        denominator = (((((((5226.495278852545925 * r + 28729.085735721942674) * r + 39307.89580009271061) * r
                           + 21213.794301586595867) * r + 5394.1960214247511077) * r + 687.1870074920579083) * r
                        + 42.313330701600911252) * r + 1.0)
        return q * numerator / denominator
    r = p if q < 0 else 1.0 - p
    r = math.sqrt(-math.log(r))
    if r <= 5.0:
        r -= 1.6
        numerator = (((((((7.7454501427834140764e-4 * r + 0.0227238449892691845833) * r + 0.24178072517745061177) * r
                         + 1.27045825245236838258) * r + 3.64784832476320460504) * r + 5.7694972214606914055) * r
                      + 4.6303378461565452959) * r + 1.42343711074968357734)
        denominator = (((((((1.05075007164441684324e-9 * r + 5.475938084995344946e-4) * r + 0.0151986665636164571966) * r
                           + 0.14810397642748007459) * r + 0.68976733498510000455) * r + 1.6763848301838038494) * r
                        + 2.05319162663775882187) * r + 1.0)
    else:
        r -= 5.0
        numerator = (((((((2.01033439929228813265e-7 * r + 2.71155556874348757815e-5) * r + 0.0012426609473880784386) * r
                         + 0.026532189526576123093) * r + 0.29656057182850489123) * r + 1.7848265399172913358) * r
                      + 5.4637849111641143699) * r + 6.6579046435011037772)
        denominator = (((((((2.04426310338993978564e-15 * r + 1.4215117583164458887e-7) * r + 1.8463183175100546818e-5) * r
                           + 7.868691311456132591e-4) * r + 0.0148753612908506148525) * r + 0.13692988092273580531) * r
                        + 0.59983220655588793769) * r + 1.0)
    value = numerator / denominator
    return -value if q < 0 else value


# ---- incomplete gamma

def _poisson_pmf_real(a: float, y: float) -> float:
    """exp(-y) y^a / Gamma(a + 1) for real a >= 0, y >= 0."""
    if y <= 0:
        return 1.0 if a == 0 else 0.0
    if a >= 20:
        return math.exp(a * _log1pmx((y - a) / a)) / math.sqrt(_TWO_PI * a) * math.exp(-_stirling(a))
    exponent = -y + a * math.log(y) - math.lgamma(a + 1.0)
    return math.exp(exponent) if exponent > -745 else 0.0


def _gamma_pq(a: float, x: float) -> tuple[float, float]:
    """Regularised lower and upper incomplete gamma (P, Q) with the small tail computed directly."""
    if x <= 0:
        return 0.0, 1.0
    if a >= 100:
        a1 = a - 1.0
        sqrt_a1 = math.sqrt(a1)
        distance = (x - a1) / sqrt_a1
        if a >= 1e6 and abs(distance) > 40:
            return (1.0, 0.0) if distance > 0 else (0.0, 1.0)
        if abs(distance) <= 6.0:
            if x > a1:
                upper = max(a1 + 11.5 * sqrt_a1, x + 6.0 * sqrt_a1)
            else:
                upper = max(0.0, min(a1 - 7.5 * sqrt_a1, x - 5.0 * sqrt_a1))

            def density(t: float) -> float:
                return math.exp(a1 * _log1pmx((t - a1) / a1)) if t > 0 else 0.0

            answer = (_gl_integral(density, x, upper, 2.0 * sqrt_a1)
                      * math.exp(-0.5 * math.log(_TWO_PI * a1) - _stirling(a1)))
            if x > a1:
                answer = min(1.0, max(0.0, answer))
                return 1.0 - answer, answer
            answer = min(1.0, max(0.0, -answer))
            return answer, 1.0 - answer
    prefactor = a * _poisson_pmf_real(a, x)  # exp(-x) x^a / Gamma(a)
    limit = min(2_000_000, int(2000 + 200 * math.sqrt(a)))
    if x < a + 1.0:
        total = term = 1.0 / a
        ap = a
        for _ in range(limit):
            ap += 1.0
            term *= x / ap
            total += term
            if term < total * 1e-17:
                break
        lower = min(1.0, total * prefactor)
        return lower, max(0.0, 1.0 - lower)
    if prefactor == 0.0:
        return 1.0, 0.0
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, limit):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    upper_tail = min(1.0, prefactor * h)
    return max(0.0, 1.0 - upper_tail), upper_tail


# ---- incomplete beta

def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, min(2_000_000, int(2000 + 200 * math.sqrt(max(a, b))))):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            return h
    raise dax_typed._error(_WRONG.format("BETA"))


def _log_ratio(x: float, centre: float) -> float:
    """ln(x / centre), accurate near 1."""
    ratio = x / centre
    return math.log1p((x - centre) / centre) if 0.5 < ratio < 2.0 else math.log(ratio)


def _log_peak_density(a: float, b: float) -> float:
    """(a - 1) ln mu + (b - 1) ln (1 - mu) - ln B(a, b), mu = a / (a + b), for a, b >= 20."""
    total = a + b
    corr = _stirling(a) + _stirling(b) - _stirling(total)
    return 0.5 * (3.0 * math.log(total) - math.log(_TWO_PI) - math.log(a) - math.log(b)) - corr 


def _beta_pq(a: float, b: float, x: float, y: float) -> tuple[float, float]:
    """Regularised incomplete beta (I_x(a, b), 1 - I_x(a, b)); y = 1 - x is supplied for accuracy."""
    if x <= 0:
        return 0.0, 1.0
    if y <= 0:
        return 1.0, 0.0
    if a > 3000 and b > 3000:
        mu = a / (a + b)
        sigma = math.sqrt((a / (a + b)) * (b / (a + b)) / (a + b + 1.0))
        if sigma <= 1e-15 * min(mu, 1.0 - mu):
            return (1.0, 0.0) if x > mu else (0.0, 1.0) if x < mu else (0.5, 0.5)
        distance = (x - mu) / sigma
        if abs(distance) > 40:
            return (1.0, 0.0) if distance > 0 else (0.0, 1.0)
        if abs(distance) <= 6.0:
            if x > mu:
                upper = min(1.0, max(mu + 10.0 * sigma, x + 5.0 * sigma))
            else:
                upper = max(0.0, min(mu - 10.0 * sigma, x - 5.0 * sigma))
            mu_c = b / (a + b)

            def density(t: float) -> float:
                if t <= 0 or t >= 1:
                    return 0.0
                offset = t - mu
                return math.exp((a - 1.0) * math.log1p(offset / mu) + (b - 1.0) * math.log1p(-offset / mu_c))

            answer = _gl_integral(density, x, upper, 2.0 * sigma) * math.exp(_log_peak_density(a, b))
            if x > mu:
                answer = min(1.0, max(0.0, answer))
                return 1.0 - answer, answer
            answer = min(1.0, max(0.0, -answer))
            return answer, 1.0 - answer
    if a >= 20 and b >= 20:
        mu = a / (a + b)
        exponent = (a * _log_ratio(x, mu) + b * _log_ratio(y, 1.0 - mu)
                    + _log_peak_density(a, b) + math.log(mu) + math.log(1.0 - mu))
    else:
        log_x = math.log1p(-y) if y < 0.5 else math.log(x)
        log_y = math.log1p(-x) if x < 0.5 else math.log(y)
        exponent = -_lbeta(a, b) + a * log_x + b * log_y
    factor = math.exp(exponent) if exponent > -745 else 0.0
    if x < (a + 1.0) / (a + b + 2.0):
        lower = min(1.0, factor * _betacf(a, b, x) / a)
        return lower, max(0.0, 1.0 - lower)
    upper_tail = min(1.0, factor * _betacf(b, a, y) / b)
    return max(0.0, 1.0 - upper_tail), upper_tail


def _beta_log_pdf(a: float, b: float, u: float) -> float:
    """ln of the Beta(a, b) density at 0 < u < 1."""
    if a >= 20 and b >= 20:
        mu = a / (a + b)
        return ((a - 1.0) * _log_ratio(u, mu) + (b - 1.0) * _log_ratio(1.0 - u, 1.0 - mu)
                + _log_peak_density(a, b))
    log_one_minus = math.log1p(-u) if u < 0.5 else math.log(1.0 - u)
    return (a - 1.0) * math.log(u) + (b - 1.0) * log_one_minus - _lbeta(a, b)


# ---- Student t

_T_TERMS = (
    (0.25, 0.0, 0.25, 0.0),
    (1 / 32, 0.0, -7 / 96, 0.0, -5 / 96, 0.0, -1 / 32, 0.0),
    (1 / 384, 0.0, -11 / 384, 0.0, 7 / 192, 0.0, 1 / 64, 0.0, -1 / 128, 0.0, -5 / 128, 0.0),
    (1 / 6144, 0.0, -25 / 6144, 0.0, 445 / 18432, 0.0, -2141 / 92160, 0.0, -313 / 30720, 0.0, -71 / 30720, 0.0,
     61 / 6144, 0.0, 21 / 2048, 0.0),
)
_T_LARGE = 2e6


def _t_upper(t: float, v: float) -> float:
    """P(T > t) for t >= 0 and v >= 1 degrees of freedom."""
    if t == 0:
        return 0.5
    if v >= _T_LARGE:
        total = 0.0
        for order, coefficients in enumerate(_T_TERMS, start=1):
            polynomial = 0.0
            for coefficient in coefficients:
                polynomial = polynomial * t + coefficient
            total += polynomial / v ** order
        return _norm_sf(t) + _norm_pdf(t) * total
    if v == 1:
        return math.atan(1.0 / t) / math.pi
    if v == 2:
        return 0.5 * (1.0 - t / math.sqrt(2.0 + t * t))
    square = t * t
    ratio = v / (v + square)
    complement = square / (v + square)
    lower, upper = _beta_pq(0.5 * v, 0.5, ratio, complement)
    return 0.5 * lower


def _t_cdf(x: float, v: float) -> float:
    return 1.0 - _t_upper(x, v) if x >= 0 else _t_upper(-x, v)


def _t_pdf(x: float, v: float) -> float:
    if v == 1:
        return 1.0 / (math.pi * (1.0 + x * x))
    log_density = (_lgamma_half_step(0.5 * v) - 0.5 * math.log(v * math.pi)
                   - 0.5 * (v + 1.0) * math.log1p(x * x / v))
    return math.exp(log_density)


def _t_upper_inv(q: float, v: float) -> float:
    """t >= 0 with P(T > t) = q for 0 < q < 0.5."""
    if v == 1:
        return 1.0 / math.tan(math.pi * q)
    if v == 2:
        return (1.0 - 2.0 * q) / math.sqrt(2.0 * q * (1.0 - q))
    start = max(-_norm_inv(q), 1e-6)
    start *= 1.0 + 0.25 / v * (start * start + 1.0)

    def tail(s: float) -> tuple[float, float]:
        t = math.exp(s)
        value = _t_upper(t, v)
        return value, -t * _t_pdf(t, v)

    return math.exp(_solve_log(tail, math.log(q), math.log(start), decreasing=True))


# ---- generic monotone solver on a log scale

def _solve_log(function, target_log: float, s0: float, decreasing: bool, high: float = math.inf) -> float:
    """Solve ln(tail(e^s)) = ln(target) for s; ``function(s)`` returns (tail, d tail / d s).

    Newton steps on the log scale, safeguarded by a bracket and bisection; ``decreasing`` says the tail falls with s.
    """
    low = -math.inf
    s = min(s0, high)
    for _ in range(300):
        value, slope = function(s)
        if value > 0:
            gap = math.log(value) - target_log
            slope_log = slope / value
        else:
            gap, slope_log = -math.inf, 0.0
        if gap == 0:
            return s
        if (gap < 0) == decreasing:
            high = min(high, s)  # the tail is on the wrong side of the target: the root lies to the left
        else:
            low = max(low, s)
        candidate = None
        if slope_log != 0.0 and math.isfinite(gap):
            candidate = s - max(-6.0, min(6.0, gap / slope_log))
            if not low < candidate < high:
                candidate = None
        if candidate is None:
            if math.isfinite(low) and math.isfinite(high):
                candidate = 0.5 * (low + high)
            elif math.isfinite(low):
                candidate = low + max(1.0, abs(low) * 0.5)
            elif math.isfinite(high):
                candidate = high - max(1.0, abs(high) * 0.5)
            else:
                candidate = s + 1.0
        if abs(candidate - s) <= 1e-15 * max(1.0, abs(s)):
            return candidate
        s = candidate
    return s


# ------------------------------------------------------------------------------------------ function groups

_T_DF_LIMIT = 10_000_000_000


def _norm(function: str, args: list[object]) -> Decimal:
    if function == "NORM.S.DIST":
        z = _number(args[0], function)
        return _result(_norm_cdf(z) if _flag(args[1]) else _norm_pdf(z), function)
    if function == "NORM.S.INV":
        p = _number(args[0], function)
        if not 0 < p < 1:
            raise _wrong(function)
        return _result(_norm_inv(p), function)
    if function == "NORM.DIST":
        x, mean, deviation = (_number(arg, function) for arg in args[:3])
        cumulative = _flag(args[3])
        if deviation <= 0:
            raise _wrong(function)
        diff = x - mean
        if math.isinf(diff):
            raise _wrong(function)
        z = diff / deviation
        return _result(_norm_cdf(z) if cumulative else _norm_pdf(z) / deviation, function)
    p, mean, deviation = (_number(arg, function) for arg in args)
    if not 0 < p < 1 or deviation <= 0:
        raise _wrong(function)
    return _result(mean + deviation * _norm_inv(p), function)


def _t_df(value: object, function: str, cumulative: bool = True) -> float:
    df = _integer(value, function)
    if df < 1 or (cumulative and df > _T_DF_LIMIT):
        raise _wrong(function)
    return float(df)


def _student(function: str, args: list[object]) -> Decimal:
    if function == "T.DIST":
        x = _number(args[0], function)
        cumulative = _flag(args[2])
        v = _t_df(args[1], function, cumulative)
        if abs(x) > _SQRT_MAX:
            if cumulative:
                raise _wrong(function)
            raise _overflow(function)
        if not cumulative:
            if v == 1 and math.isinf(math.pi * (1.0 + x * x)):
                raise _divide(function)
            return _result(_t_pdf(x, v), function)
        return _result(_t_cdf(x, v), function)
    if function in {"T.DIST.2T", "T.DIST.RT"}:
        x = _number(args[0], function)
        v = _t_df(args[1], function)
        if abs(x) > _SQRT_MAX or (function == "T.DIST.2T" and x < 0):
            raise _wrong(function)
        if function == "T.DIST.RT":
            return _result(1.0 - _t_cdf(x, v) if x < 0 else _t_upper(x, v), function)
        return _result(min(1.0, 2.0 * _t_upper(x, v)), function)
    p = _number(args[0], function)
    v = _t_df(args[1], function)
    if function == "T.INV":
        if not 0 < p < 1 or p < _DBL_MIN:
            raise _wrong(function)
        if p == 0.5:
            return Decimal(0)
        if v == 1 and p in (0.25, 0.75):
            raise _divide(function)
        t = _t_upper_inv(1.0 - p, v) if p > 0.5 else -_t_upper_inv(p, v)
        return _result(t, function)
    # T.INV.2T
    if p < 0 or p >= 2:
        raise _wrong(function)
    if p / 2.0 < _DBL_MIN:
        raise _overflow(function)
    if p == 1:
        return Decimal(0)
    if v == 1 and p in (0.5, 1.5):
        raise _divide(function)
    t = _t_upper_inv(p / 2.0, v) if p < 1 else -_t_upper_inv((2.0 - p) / 2.0, v)
    return _result(t, function)


_CHISQ_RT_GAP = (1.15e10, 3.95e10)
_CHISQ_RT_APPROXIMATION = 2.6582355057e-4


def _chisq_df(value: object, function: str, limit: bool = True) -> float:
    df = _integer(value, function)
    if df < 1 or (limit and df > _T_DF_LIMIT):
        raise _wrong(function)
    return float(df)


def _gamma_quantile(p: float, q: float, a: float) -> float:
    """y with P(a, y) = p (q = 1 - p); a > 0, 0 < p < 1."""
    use_lower = p <= 0.5
    z = _norm_inv(p) if use_lower else -_norm_inv(q)
    if a >= 1e11:  # Cornish-Fisher expansion of the chi-square quantile is exact to far below 1e-9 here
        degrees = 2.0 * a
        root = math.sqrt(2.0 * degrees)
        half = 0.5 * root
        del half
        return 0.5 * (degrees + z * math.sqrt(2.0 * degrees) + (2.0 / 3.0) * (z * z - 1.0)
                      + (z ** 3 - 7.0 * z) / (9.0 * math.sqrt(2.0 * degrees)))
    start = a * (1.0 - 1.0 / (9.0 * a) + z / (3.0 * math.sqrt(a))) ** 3
    if not start > 0 or a < 1.0:
        lower_p = p if use_lower else None
        if lower_p is not None and lower_p > 0:
            start = math.exp((math.log(lower_p) + math.lgamma(a + 1.0)) / a)
        else:
            start = max(a, 1e-3)
        if not 0 < start < 1e300:
            start = max(a, 1e-3)

    def lower(s: float) -> tuple[float, float]:
        y = math.exp(min(s, 709.0))
        value = _gamma_pq(a, y)[0]
        density = (a / y) * _poisson_pmf_real(a, y) if y > 0 else 0.0
        return value, y * density

    def upper(s: float) -> tuple[float, float]:
        y = math.exp(min(s, 709.0))
        value = _gamma_pq(a, y)[1]
        density = (a / y) * _poisson_pmf_real(a, y) if y > 0 else 0.0
        return value, -y * density

    if use_lower:
        s = _solve_log(lower, math.log(p), math.log(start), decreasing=False)
    else:
        s = _solve_log(upper, math.log(q), math.log(start), decreasing=True)
    return math.exp(s)


def _chisq(function: str, args: list[object]) -> Decimal | None:
    if function == "CHISQ.DIST":
        x = _number(args[0], function)
        cumulative = _flag(args[2])
        v = _chisq_df(args[1], function)
        if x < 0:
            raise _wrong(function)
        a = 0.5 * v
        if cumulative:
            value = _gamma_pq(a, 0.5 * x)[0]
        elif 0.5 * x == 0:
            if v == 1:
                raise _wrong(function)
            value = 0.5 if v == 2 else 0.0
        else:
            y = 0.5 * x
            value = 0.5 * (a / y) * _poisson_pmf_real(a, y)
        return None if args[0] is None and value == 0 else _result(value, function)
    if function == "CHISQ.DIST.RT":
        x = _number(args[0], function)
        v = _chisq_df(args[1], function)
        if x < 0:
            raise _wrong(function)
        return _result(_gamma_pq(0.5 * v, 0.5 * x)[1], function)
    p = _number(args[0], function)
    if function == "CHISQ.INV":
        v = _chisq_df(args[1], function)
        if not 0 <= p < 1:
            raise _wrong(function)
        if p == 0:
            return None if args[0] is None else Decimal(0)
        return _result(2.0 * _gamma_quantile(p, 1.0 - p, 0.5 * v), function)
    # CHISQ.INV.RT
    v = _chisq_df(args[1], function, limit=False)
    if not 0 < p <= 1:
        raise _wrong(function)
    if _CHISQ_RT_GAP[0] < v < _CHISQ_RT_GAP[1]:
        raise _wrong(function)
    if p == 1:
        return Decimal(0)
    value = 2.0 * _gamma_quantile(1.0 - p, p, 0.5 * v)
    if v >= _CHISQ_RT_GAP[1]:
        value += _CHISQ_RT_APPROXIMATION * v
    return _result(value, function)


def _beta(function: str, args: list[object]) -> Decimal | None:
    if function == "BETA.DIST":
        x, a, b = (_number(arg, function) for arg in args[:3])
        cumulative = _flag(args[3])
        low = _number(args[4], function) if len(args) > 4 else 0.0
        high = _number(args[5], function) if len(args) > 5 else 1.0
        if a <= 0 or b <= 0 or low >= high or not low <= x <= high:
            raise _wrong(function)
        width = high - low
        if math.isinf(width):
            raise _divide(function)
        u = (x - low) / width
        if u <= 0:
            if cumulative:
                value = 0.0
            elif a <= 1:
                raise _wrong(function)
            else:
                value = 0.0
        elif u >= 1:
            if cumulative:
                value = 1.0
            elif b <= 1:
                raise _wrong(function)
            else:
                value = 0.0
        elif cumulative:
            value = _beta_pq(a, b, u, 1.0 - u)[0]
        else:
            log_density = _beta_log_pdf(a, b, u)
            value = math.exp(log_density) / width if log_density < 709 else math.inf
        return None if args[0] is None and value == 0 else _result(value, function)
    p, a, b = (_number(arg, function) for arg in args[:3])
    low = _number(args[3], function) if len(args) > 3 else 0.0
    high = _number(args[4], function) if len(args) > 4 else 1.0
    if not 0 < p < 1 or a <= 0 or b <= 0 or low >= high:
        raise _wrong(function)
    width = high - low
    if math.isinf(width):
        raise _divide(function)
    return _result(low + width * _beta_quantile(p, a, b), function)


def _beta_quantile(p: float, a: float, b: float) -> float:
    """x in (0, 1) with I_x(a, b) = p."""
    if p > 0.5:
        return 1.0 - _beta_quantile_lower(1.0 - p, b, a, upper_only=True)
    return _beta_quantile_lower(p, a, b, upper_only=False)


def _beta_quantile_lower(p: float, a: float, b: float, upper_only: bool) -> float:
    mean = a / (a + b)
    z = _norm_inv(p)
    spread = math.sqrt((a / (a + b)) * (b / (a + b)) / (a + b + 1.0))
    start = mean + z * spread
    if not 1e-12 < start < 1.0 - 1e-12 or a < 1.0 or b < 1.0:
        start = min(max(mean, 1e-300), 0.5)
        if p < 0.5:
            tail_guess = math.exp((math.log(p) + math.log(a) + _lbeta(a, b)) / a)
            if 0 < tail_guess < 0.9:
                start = tail_guess

    def lower(s: float) -> tuple[float, float]:
        if s < -740.0:
            return 0.0, 0.0
        x = math.exp(s)
        if x >= 1.0:
            return 1.0, 0.0
        value = _beta_pq(a, b, x, 1.0 - x)[0]
        log_density = _beta_log_pdf(a, b, x)
        return value, x * math.exp(min(log_density, 700.0)) if log_density > -745 else 0.0

    s = _solve_log(lower, math.log(p), math.log(start), decreasing=False, high=0.0)
    del upper_only
    return min(math.exp(s), 1.0)


def _expon(args: list[object]) -> Decimal | None:
    function = "EXPON.DIST"
    x, rate = _number(args[0], function), _number(args[1], function)
    cumulative = _flag(args[2])
    if rate <= 0 or x < 0:
        raise _wrong(function)
    product = rate * x
    value = -math.expm1(-product) if cumulative else rate * math.exp(-product)
    return None if args[0] is None and value == 0 else _result(value, function)


def _poisson_pmf(k: float, mean: float) -> float:
    if mean == 0:
        return 1.0 if k == 0 else 0.0
    if k >= 20:
        return math.exp(k * _log1pmx((mean - k) / k)) / math.sqrt(_TWO_PI * k) * math.exp(-_stirling(k))
    exponent = -mean + k * math.log(mean) - math.lgamma(k + 1.0)
    return math.exp(exponent) if exponent > -745 else 0.0


def _poisson(args: list[object]) -> Decimal:
    function = "POISSON.DIST"
    k = _integer(args[0], function)
    mean = _number(args[1], function)
    cumulative = _flag(args[2])
    if k < 0:
        raise _overflow(function)
    if mean < 0:
        raise _wrong(function)
    if not cumulative:
        return _result(_poisson_pmf(float(k), mean), function)
    if mean == 0:
        return Decimal(1)
    return _result(_gamma_pq(float(k) + 1.0, mean)[1], function)


def _confidence(function: str, args: list[object]) -> Decimal:
    alpha, deviation = _number(args[0], function), _number(args[1], function)
    size = _integer(args[2], function)
    if not 0 < alpha < 1 or deviation <= 0 or size < 1:
        raise _wrong(function)
    if function == "CONFIDENCE.NORM":
        z = _norm_inv(1.0 - alpha / 2.0) if 1.0 - alpha / 2.0 < 1.0 else math.nan
        if math.isnan(z):
            raise _wrong(function)
        return _result(z * deviation / math.sqrt(size), function)
    if size < 2 or size - 1 > _T_DF_LIMIT:
        raise _wrong(function)
    df = float(size - 1)
    if alpha / 2.0 < _DBL_MIN:
        raise _wrong(function)
    if df == 1 and alpha == 0.5:
        raise _divide(function)
    t = _t_upper_inv(alpha / 2.0, df) if alpha < 1 else 0.0
    return _result(t * deviation / math.sqrt(size), function)


def call(function: str, args: list[object]) -> object:
    from .measures import MeasureError  # imported late: measures imports this module

    try:
        return _dispatch(function, args)
    except MeasureError:
        raise
    except (OverflowError, ZeroDivisionError, ValueError):
        raise _wrong(function) from None


def _dispatch(function: str, args: list[object]) -> object:
    if function.startswith("NORM."):
        return _norm(function, args)
    if function.startswith("T."):
        return _student(function, args)
    if function.startswith("CHISQ."):
        return _chisq(function, args)
    if function.startswith("BETA."):
        return _beta(function, args)
    if function == "EXPON.DIST":
        return _expon(args)
    if function == "POISSON.DIST":
        return _poisson(args)
    if function.startswith("CONFIDENCE."):
        return _confidence(function, args)
    raise KeyError(function)
