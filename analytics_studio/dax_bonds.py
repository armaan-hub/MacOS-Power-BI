"""DAX bond and security functions, matching Power BI Desktop 2.157.879.0 (see analytics_studio/dax_ext.py for the module contract).

Compared live through ``tools/dax_battery_bonds.json``.  Dates arrive as DateTime values (days since 1899-12-30); only the whole
day counts.  The day-count ``basis`` follows the spreadsheet convention (0 US 30/360, 1 actual/actual, 2 actual/360,
3 actual/365, 4 European 30/360).
"""

from __future__ import annotations

from calendar import isleap, monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR
import math

from analytics_studio import dax_dates, dax_typed

ARITY: dict[str, tuple[int, int]] = {
    "ACCRINT": (6, 8),
    "ACCRINTM": (4, 5),
    "AMORDEGRC": (6, 7),
    "AMORLINC": (6, 7),
    "COUPDAYBS": (3, 4),
    "COUPDAYS": (3, 4),
    "COUPDAYSNC": (3, 4),
    "COUPNCD": (3, 4),
    "COUPNUM": (3, 4),
    "COUPPCD": (3, 4),
    "DISC": (4, 5),
    "DURATION": (5, 6),
    "INTRATE": (4, 5),
    "MDURATION": (5, 6),
    "ODDFPRICE": (8, 9),
    "ODDLPRICE": (7, 8),
    "ODDLYIELD": (7, 8),
    "PRICE": (6, 7),
    "PRICEDISC": (4, 5),
    "PRICEMAT": (5, 6),
    "RECEIVED": (4, 5),
    "TBILLEQ": (3, 3),
    "TBILLPRICE": (3, 3),
    "TBILLYIELD": (3, 3),
    "YIELD": (6, 7),
    "YIELDDISC": (4, 5),
    "YIELDMAT": (5, 6),
}
CATEGORY: dict[str, str] = {"COUPNCD": "date/time", "COUPPCD": "date/time"}

# ODDFYIELD is implemented below (``_odd_first``) but deliberately not listed in ARITY: Power BI's own ODDFYIELD is not the
# inverse of its ODDFPRICE for some inputs (settlement a few days before the first coupon, month-end dates, some prices far
# from par) and sometimes raises where a root exists, so the app refuses the function rather than answer differently.

_EPOCH = date(1899, 12, 30)


def _fail(function: str) -> Exception:
    return dax_typed._error(
        f"An argument of function '{function}' has the wrong data type or the result is too large or too small."
    )


# ------------------------------------------------------------------------------------------------ arguments


class _Ctx:
    """Argument conversion for one call (the function name is only used in error messages)."""

    def __init__(self, function: str) -> None:
        self.function = function

    def fail(self) -> Exception:
        return _fail(self.function)

    def date(self, value: object) -> int:
        """A date argument as a whole serial day (the time of day is dropped)."""
        if isinstance(value, str):
            serial = dax_dates.parse_date_text(value)
        else:
            serial = dax_typed.to_number(value)
        if not serial.is_finite():
            raise self.fail()
        return int(serial.to_integral_value(rounding=ROUND_FLOOR))

    def number(self, value: object) -> float:
        number = dax_typed.to_number(value)
        if not number.is_finite():
            raise self.fail()
        return float(number)

    def whole(self, value: object) -> int:
        try:
            return dax_typed.whole(value, self.function)
        except Exception as exc:  # noqa: BLE001 - a non-finite count is the same failure as any other bad argument
            if type(exc).__name__ == "MeasureRuntimeError" and "has the wrong data type or has an invalid value" in str(exc):
                raise self.fail() from exc
            raise

    def basis(self, args: list[object], index: int) -> int:
        value = self.whole(args[index]) if len(args) > index else 0
        if not 0 <= value <= 4:
            raise self.fail()
        return value

    def flag(self, value: object) -> bool:
        """A TRUE/FALSE argument: blank is TRUE here; text reads as TRUE/FALSE or as a number."""
        if value is None:
            return True
        if isinstance(value, str):
            text = value.casefold()
            if text in ("true", "false"):
                return text == "true"
            return dax_typed.text_to_number(value) != 0
        return dax_typed.to_boolean(value)

    def frequency(self, value: object) -> int:
        freq = self.whole(value)
        if freq not in (1, 2, 4):
            raise self.fail()
        return freq


def _date_of(serial: int, ctx: _Ctx) -> date:
    try:
        return _EPOCH + timedelta(days=serial)
    except OverflowError as exc:
        raise ctx.fail() from exc


def _serial_of(day: date) -> int:
    return (day - _EPOCH).days


# ------------------------------------------------------------------------------------------------ day counts


def _last_day(day: date) -> bool:
    return day.day == monthrange(day.year, day.month)[1]


def _days360(start: date, end: date, european: bool) -> int:
    """Days between two dates on a 30-day month basis (``european`` is basis 4, otherwise the US/NASD method)."""
    return _eu360(start, end) if european else _us360(start, end, False)


def _days_between(start: int, end: int, basis: int, ctx: _Ctx) -> int:
    """Day count from start to end under the basis (negative when end is before start)."""
    if basis in (0, 4):
        a, b = _date_of(start, ctx), _date_of(end, ctx)
        if start <= end:
            return _days360(a, b, basis == 4)
        return -_days360(b, a, basis == 4)
    return end - start


def _year_length(start: int, end: int, basis: int, ctx: _Ctx) -> float:
    """The number of days in a year for the interval (YEARFRAC's denominator)."""
    if basis in (0, 2, 4):
        return 360.0
    if basis == 3:
        return 365.0
    if start > end:
        start, end = end, start
    a, b = _date_of(start, ctx), _date_of(end, ctx)
    if a.year == b.year:
        return 366.0 if isleap(a.year) else 365.0
    within_year = b.year == a.year + 1 and (a.month, a.day) >= (b.month, b.day)
    if within_year:
        if isleap(a.year) and (a.month, a.day) <= (2, 29):
            return 366.0
        if isleap(b.year) and (b.month, b.day) >= (2, 29):
            return 366.0
        return 365.0
    years = range(a.year, b.year + 1)
    return sum(366 if isleap(year) else 365 for year in years) / len(years)


def _yearfrac(start: int, end: int, basis: int, ctx: _Ctx) -> float:
    return _days_between(start, end, basis, ctx) / _year_length(start, end, basis, ctx)


# ------------------------------------------------------------------------------------------------ coupons


def _shift_months(anchor: date, months: int, end_of_month: bool, ctx: _Ctx) -> date:
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if not 1 <= year <= 9999:
        raise ctx.fail()
    last = monthrange(year, month)[1]
    return date(year, month, last if end_of_month else min(anchor.day, last))


def _change_month(day: date, months: int, end_of_month: bool, ctx: _Ctx) -> date:
    """Move by whole months, clipping the day to the month; with ``end_of_month`` the result is the last day of that month."""
    return _shift_months(day, months, end_of_month, ctx)


def _days360_both(start: date, end: date) -> int:
    """30/360 US days with the February and 31st rules applied to both dates (used for coupon period lengths)."""
    d1, d2 = start.day, end.day
    if end.month == 2 and _last_day(end):
        d2 = 30
    if d2 == 31:
        d2 = 30
    if d1 == 31:
        d1 = 30
    if start.month == 2 and _last_day(start):
        d1 = 30
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1)


def _numerator_days(start: date, end: date, basis: int) -> float:
    """Days from start to end under the basis (may be negative)."""
    if basis == 0:
        return float(_days360(start, end, False)) if start <= end else -float(_days360(end, start, False))
    if basis == 4:
        return float(_days360(start, end, True)) if start <= end else -float(_days360(end, start, True))
    return float((end - start).days)


class _Coupons:
    """The coupon schedule of a security (dates stepped back from maturity)."""

    def __init__(self, settlement: int, maturity: int, frequency: int, ctx: _Ctx) -> None:
        self.ctx = ctx
        self.frequency = frequency
        self.step = 12 // frequency
        self.maturity_date = _date_of(maturity, ctx)
        self.end_of_month = _last_day(self.maturity_date)
        settle = _date_of(settlement, ctx)
        months = (self.maturity_date.year - settle.year) * 12 + self.maturity_date.month - settle.month
        k = max(months // self.step, 1)
        while self.at(k) > settle:  # the smallest k whose date is on or before settlement
            k += 1
        while k > 1 and self.at(k - 1) <= settle:
            k -= 1
        self.count = k
        self.previous = self.at(k)
        self.next = self.at(k - 1)

    def at(self, k: int) -> date:
        return _shift_months(self.maturity_date, -k * self.step, self.end_of_month, self.ctx)


def _actual_period_days(c: _Coupons, settlement: date) -> float:
    """COUPDAYS for the actual basis.

    Power BI does not take this from the previous and next coupon dates: it steps back from maturity one period at a time
    (each step clips the day to the month), takes the first date after settlement, then measures back one period with the
    end-of-month rule; when that lands after settlement it steps back once more.
    """
    step = c.step
    next_date = c.maturity_date
    while True:
        earlier = _shift_months(next_date, -step, False, c.ctx)
        if earlier <= settlement:
            break
        next_date = earlier
    back = _shift_months(next_date, -step, _last_day(next_date), c.ctx)
    while back > settlement:
        next_date = back
        back = _shift_months(next_date, -step, _last_day(next_date), c.ctx)
    return float((next_date - back).days)


def _coupon_days_in_period(c: _Coupons, basis: int, settlement: date | None = None, *, quirk: bool = False) -> float:
    """Days in the coupon period (COUPDAYS); ``quirk`` is Power BI's own COUPDAYS day count for the actual basis."""
    if basis == 1:
        if quirk:
            return _actual_period_days(c, settlement)  # type: ignore[arg-type]
        return float((c.next - c.previous).days)
    return (365.0 if basis == 3 else 360.0) / c.frequency


def _coupon_days_to_settlement(c: _Coupons, settlement: int, basis: int) -> float:
    return float(_days_between(_serial_of(c.previous), settlement, basis, c.ctx))


def _coupon_days_to_next(c: _Coupons, settlement: int, basis: int) -> float:
    if basis == 0:
        return _coupon_days_in_period(c, basis) - _coupon_days_to_settlement(c, settlement, basis)
    return float(_days_between(settlement, _serial_of(c.next), basis, c.ctx))


# ------------------------------------------------------------------------------------------------ helpers


def _out(value: float, function: str) -> Decimal:
    if not isinstance(value, float) or math.isnan(value) or math.isinf(value):
        raise _fail(function)
    return Decimal(repr(value)) if value != 0 else Decimal(0)


# ------------------------------------------------------------------------------------------------ securities


def _discount_family(function: str, args: list[object], ctx: _Ctx) -> object:
    settlement, maturity = ctx.date(args[0]), ctx.date(args[1])
    first, second = ctx.number(args[2]), ctx.number(args[3])
    basis = ctx.basis(args, 4)
    if settlement >= maturity:
        raise ctx.fail()
    fraction = _yearfrac(settlement, maturity, basis, ctx)
    if function == "DISC":  # price, redemption
        if first <= 0 or second <= 0:
            raise ctx.fail()
        return _out((1.0 - first / second) / fraction, function)
    if function == "INTRATE":  # investment, redemption
        if first <= 0 or second <= 0:
            raise ctx.fail()
        return _out(((second / first) - 1.0) / fraction, function)
    if function == "RECEIVED":  # investment, discount
        if first <= 0 or second <= 0 or second * fraction >= 1.0:
            raise ctx.fail()
        return _out(first / (1.0 - second * fraction), function)
    if function == "PRICEDISC":  # discount, redemption
        if first <= 0 or second <= 0:
            raise ctx.fail()
        return _out(second * (1.0 - first * fraction), function)
    # YIELDDISC: price, redemption
    if first <= 0 or second <= 0:
        raise ctx.fail()
    return _out((second / first - 1.0) / fraction, function)


def _tbill(function: str, args: list[object], ctx: _Ctx) -> object:
    settlement, maturity = ctx.date(args[0]), ctx.date(args[1])
    value = ctx.number(args[2])
    if settlement >= maturity or value <= 0:
        raise ctx.fail()
    start = _date_of(settlement, ctx)
    limit = _shift_months(start, 12, False, ctx)
    if _date_of(maturity, ctx) > limit:
        raise ctx.fail()
    days = float(maturity - settlement)
    if function == "TBILLPRICE":
        price = 100.0 * (1.0 - value * days / 360.0)
        if price <= 0:
            raise ctx.fail()
        return _out(price, function)
    if function == "TBILLYIELD":
        return _out((100.0 - value) / value * (360.0 / days), function)
    if days <= 182.0:
        result = 365.0 * value / (360.0 - value * days)
        if 360.0 - value * days <= 0:
            raise ctx.fail()
        return _out(result, function)
    price = 100.0 * (1.0 - value * days / 360.0)
    if price <= 0:
        raise ctx.fail()
    half = days / (366.0 if days > 365 else 365.0)
    root = half * half - (2.0 * half - 1.0) * (1.0 - 100.0 / price)
    return _out((-half + math.sqrt(root)) / (half - 0.5), function)


def _accrintm(args: list[object], ctx: _Ctx) -> object:
    issue, settlement = ctx.date(args[0]), ctx.date(args[1])
    rate, par = ctx.number(args[2]), ctx.number(args[3])
    basis = ctx.basis(args, 4)
    if rate <= 0 or par <= 0 or issue >= settlement:
        raise ctx.fail()
    return _out(par * rate * _yearfrac(issue, settlement, basis, ctx), "ACCRINTM")


def _pricemat(function: str, args: list[object], ctx: _Ctx) -> object:
    settlement, maturity, issue = ctx.date(args[0]), ctx.date(args[1]), ctx.date(args[2])
    rate, third = ctx.number(args[3]), ctx.number(args[4])
    basis = ctx.basis(args, 5)
    if settlement >= maturity or issue >= settlement or rate < 0:
        raise ctx.fail()
    year = _year_length(issue, settlement, basis, ctx)  # one year length (taken from issue to settlement) for all three spans
    issue_to_maturity = _days_between(issue, maturity, basis, ctx)
    issue_to_settlement = _days_between(issue, settlement, basis, ctx)
    issue_maturity = issue_to_maturity / year
    issue_settlement = issue_to_settlement / year
    settlement_maturity = (issue_to_maturity - issue_to_settlement) / year  # the remaining days are the difference of the two counts
    if function == "PRICEMAT":
        if third < 0:
            raise ctx.fail()
        result = (1.0 + issue_maturity * rate) / (1.0 + settlement_maturity * third) - issue_settlement * rate
        return _out(result * 100.0, function)
    if third <= 0:
        raise ctx.fail()
    result = (1.0 + issue_maturity * rate) / (third / 100.0 + issue_settlement * rate) - 1.0
    return _out(result / settlement_maturity, function)


def _coupon_function(function: str, args: list[object], ctx: _Ctx) -> object:
    settlement, maturity = ctx.date(args[0]), ctx.date(args[1])
    frequency = ctx.frequency(args[2])
    basis = ctx.basis(args, 3)
    if settlement >= maturity:
        raise ctx.fail()
    c = _Coupons(settlement, maturity, frequency, ctx)
    if function == "COUPNCD":
        return dax_dates.from_datetime(c.next)
    if function == "COUPPCD":
        return dax_dates.from_datetime(c.previous)
    if function == "COUPNUM":
        return Decimal(c.count)
    if function == "COUPDAYBS":
        return _out(_coupon_days_to_settlement(c, settlement, basis), function)
    if function == "COUPDAYS":
        return _out(_coupon_days_in_period(c, basis, _date_of(settlement, c.ctx), quirk=True), function)
    return _out(_coupon_days_to_next(c, settlement, basis), function)


def _periodic(function: str, args: list[object], ctx: _Ctx) -> object:
    """PRICE, YIELD, DURATION and MDURATION."""
    settlement, maturity = ctx.date(args[0]), ctx.date(args[1])
    rate = ctx.number(args[2])
    if function in ("PRICE", "YIELD"):
        yield_or_price, redemption = ctx.number(args[3]), ctx.number(args[4])
        frequency = ctx.frequency(args[5])
        basis = ctx.basis(args, 6)
    else:
        yield_or_price, redemption = ctx.number(args[3]), 100.0
        frequency = ctx.frequency(args[4])
        basis = ctx.basis(args, 5)
    if settlement >= maturity or rate < 0:
        raise ctx.fail()
    if function == "YIELD":
        if yield_or_price <= 0 or redemption <= 0:
            raise ctx.fail()
    elif yield_or_price < 0 or (function == "PRICE" and redemption <= 0):
        raise ctx.fail()
    c = _Coupons(settlement, maturity, frequency, ctx)
    period = _coupon_days_in_period(c, basis, _date_of(settlement, c.ctx))
    accrued = _coupon_days_to_settlement(c, settlement, basis)
    to_next = period - accrued  # days from settlement to the next coupon, measured inside the period
    n = c.count
    coupon = 100.0 * rate / frequency

    def price_at(yld: float) -> float:
        base = 1.0 + yld / frequency
        if n == 1:
            return (redemption + coupon) / (1.0 + to_next / period * yld / frequency) - coupon * accrued / period
        total = redemption / base ** (n - 1 + to_next / period)
        for k in range(1, n + 1):
            total += coupon / base ** (k - 1 + to_next / period)
        return total - coupon * accrued / period

    if function == "PRICE":
        return _out(price_at(yield_or_price), function)
    if function == "YIELD":
        if n == 1:  # one coupon left: the price formula inverts directly
            if basis in (1, 2, 3):  # these bases measure this period by its actual length
                period = float((c.next - c.previous).days)
            remaining = float(_days_between(settlement, _serial_of(c.next), basis, ctx))
            if remaining == 0:
                raise _fail(function)
            ratio = (redemption / 100.0 + rate / frequency) / (yield_or_price / 100.0 + accrued / period * rate / frequency) - 1.0
            return _out(ratio * frequency * period / remaining, function)
        return _out(_solve_yield(price_at, yield_or_price, function, frequency), function)
    base = 1.0 + yield_or_price / frequency
    shift = to_next / period
    weighted = 0.0
    present = 0.0
    for k in range(1, n + 1):
        cash = coupon + (redemption if k == n else 0.0)
        discounted = cash / base ** (k - 1 + shift)
        weighted += (k - 1 + shift) * discounted
        present += discounted
    duration = weighted / present / frequency
    if function == "MDURATION":
        duration /= base
    return _out(duration, function)


def _solve_yield(price_at, target: float, function: str, frequency: int = 2) -> float:
    """The yield at which ``price_at`` equals ``target`` (price falls as the yield rises)."""

    def safe(yld: float) -> float:
        try:
            return price_at(yld)
        except (ZeroDivisionError, OverflowError):
            return math.inf

    low, high = 0.0, 1.0
    if safe(low) < target:
        # price above even a zero yield: a negative yield is needed (the price is unbounded as yield/frequency nears -1)
        base = 1.0
        while True:
            base /= 2.0
            low = frequency * (base - 1.0)
            if safe(low) >= target:
                break
            if base < 1e-12:
                raise _fail(function)
    while safe(high) > target:
        high *= 2.0
        if high > 1e9:
            raise _fail(function)
    for _ in range(400):
        mid = (low + high) / 2.0
        if safe(mid) > target:
            low = mid
        else:
            high = mid
        if high - low <= 1e-16 * max(1.0, abs(mid)):
            break
    return (low + high) / 2.0


def _round_excel(value: float) -> float:
    """Round half away from zero after first rounding to 13 decimals (the way Excel does)."""
    return float(Decimal(repr(value)).quantize(Decimal("1e-13"), rounding="ROUND_HALF_UP").quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def _first_depreciation(cost: float, purchased: date, first: date, salvage: float, rate: float, life: float, basis: int) -> tuple[float, float]:
    """The first (part) period's straight-line depreciation and the asset life counted in periods."""

    def fix_leap(day: date) -> date:
        if basis in (1, 3) and isleap(day.year) and day.month == 2 and day.day >= 28:
            return date(day.year, 2, 28)
        return day

    if basis == 1:
        year_days = 366.0 if isleap(purchased.year) else 365.0
    else:
        year_days = 365.0 if basis == 3 else 360.0
    length = _numerator_days(fix_leap(purchased), fix_leap(first), basis)
    first_temp = length / year_days * rate * cost
    first_depreciation = cost * rate if first_temp == 0 else first_temp
    asset_life = life if first_temp == 0 else life + 1.0
    available = cost - salvage
    return (available if first_depreciation > available else first_depreciation), asset_life


def _amortisation(function: str, args: list[object], ctx: _Ctx) -> object:
    cost = ctx.number(args[0])
    purchased_s, first_s = ctx.date(args[1]), ctx.date(args[2])
    salvage = ctx.number(args[3])
    period = ctx.whole(args[4])
    rate = ctx.number(args[5])
    basis = ctx.basis(args, 6)
    if cost <= 0 or salvage < 0 or period < 0 or rate <= 0 or purchased_s > first_s or salvage > cost or basis == 2:
        raise ctx.fail()
    if function == "AMORDEGRC" and rate >= 0.5:
        raise ctx.fail()
    purchased, first = _date_of(purchased_s, ctx), _date_of(first_s, ctx)
    life = math.ceil(1.0 / rate)
    if period > life or cost == salvage:
        return Decimal(0)
    if function == "AMORLINC":
        first_depr, _ = _first_depreciation(cost, purchased, first, salvage, rate, float(life), basis)
        if period == 0:
            return _out(first_depr, function)
        depr, available = rate * cost, cost - salvage - first_depr
        for _ in range(period):
            depr = min(depr, available)
            available = max(available - depr, 0.0)
        return _out(depr, function)
    coefficient = 1.5 if 3 <= life <= 4 else 2.0 if 5 <= life <= 6 else 2.5 if life > 6 else 1.0
    depr_rate = rate * coefficient
    first_linear, asset_life = _first_depreciation(cost, purchased, first, salvage, depr_rate, float(life), basis)
    first_depr = _round_excel(first_linear)
    if period == 0:
        return _out(first_depr, function)
    remaining = cost - first_depr
    depr = 0.0
    for counted in range(2, period + 2):
        last_two = abs(asset_life - counted - 2.0) < 0.0001
        temp = remaining * 0.5 if last_two else depr_rate * remaining
        if last_two:
            depr_rate = 1.0
        if remaining < salvage:
            depr = 0.0 if remaining - salvage < 0 else remaining - salvage
        else:
            depr = temp
        remaining -= depr
    return _out(_round_excel(depr), function)


def _us360(start: date, end: date, both: bool) -> int:
    """30/360 US day count; ``both`` applies the February and 31st rules to the end date regardless of the start date."""
    sd, ed = start.day, end.day
    if end.month == 2 and _last_day(end) and (start.month == 2 and _last_day(start) or both):
        ed = 30
    if ed == 31 and (sd >= 30 or both):
        ed = 30
    if sd == 31:
        sd = 30
    if start.month == 2 and _last_day(start):
        sd = 30
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (ed - sd)


def _eu360(start: date, end: date) -> int:
    return (end.year - start.year) * 360 + (end.month - start.month) * 30 + (min(end.day, 30) - min(start.day, 30))


def _basis_days(start: date, end: date, basis: int) -> float:
    """Days between two dates for the accrued-interest functions."""
    if basis == 0:
        return float(_us360(start, end, False))
    if basis == 4:
        return float(_eu360(start, end))
    return float((end - start).days)


def _accrint(args: list[object], ctx: _Ctx) -> object:
    issue_s, first_s, settle_s = ctx.date(args[0]), ctx.date(args[1]), ctx.date(args[2])
    rate, par = ctx.number(args[3]), ctx.number(args[4])
    frequency = ctx.frequency(args[5])
    basis = ctx.basis(args, 6)
    from_issue = True if len(args) < 8 else ctx.flag(args[7])
    if rate <= 0 or par <= 0 or issue_s >= settle_s or issue_s == 0 or first_s == 0:
        raise ctx.fail()
    issue, first, settle = _date_of(issue_s, ctx), _date_of(first_s, ctx), _date_of(settle_s, ctx)
    step = 12 // frequency
    eom = _last_day(first)

    def coupon_days(early: date, late: date) -> float:
        if basis == 1:
            return _chain_period_days(early, late, frequency, ctx)
        return (365.0 if basis == 3 else 360.0) / frequency

    before_first = _change_month(first, -step, eom, ctx)
    pcd = before_first
    if settle > first and from_issue:
        pcd = first
        while True:  # the last quasi-coupon date on or before settlement
            following = _change_month(pcd, step, eom, ctx)
            if following > settle:
                break
            pcd = following
    first_date = max(issue, pcd)
    total = _basis_days(first_date, settle, basis) / coupon_days(before_first, first)
    front = pcd
    while front > issue:
        trailing = front
        front = _change_month(trailing, -step, eom, ctx)
        begin = max(issue, front)
        span = float(_us360(begin, trailing, issue <= front)) if basis == 0 else _basis_days(begin, trailing, basis)
        if basis in (0, 2):
            period = float(_us360(front, trailing, True))
        else:
            period = 365.0 / frequency if basis == 3 else _basis_days(front, trailing, basis)
        total += (1.0 if from_issue else 0.0) if issue <= front else span / period
    return _out(par * rate / frequency * total, "ACCRINT")


def _chain_period_days(early: date, late: date, frequency: int, ctx: _Ctx) -> float:
    """Days of the coupon period of a security maturing on ``late`` and bought on ``early`` (actual basis)."""
    if late <= early:
        return float((early - late).days) if late < early else 0.0
    c = _Coupons(_serial_of(early), _serial_of(late), frequency, ctx)
    return float((c.next - c.previous).days)


# ------------------------------------------------------------------------------------------------ odd periods


def _nonneg(value: float) -> float:
    return value if value > 0 else 0.0


def _quasi_count(first: date, settle: date, step: int, ctx: _Ctx) -> int:
    """The number of whole quasi-coupon periods between settlement and the first coupon."""
    eom_first = _last_day(first)
    eom = eom_first
    if not eom_first and first.month != 2 and first.day > 28 and first.day < monthrange(first.year, first.month)[1]:
        eom = _last_day(settle)
    start = _change_month(settle, 0, eom, ctx)
    total = 1 if settle < start else 0
    front = _change_month(start, step, eom, ctx)
    while front < first:
        total += 1
        front = _change_month(front, step, eom, ctx)
    return total


def _odd_first(function: str, args: list[object], ctx: _Ctx) -> object:
    settlement, maturity, issue, first_coupon = (ctx.date(args[i]) for i in range(4))
    rate = ctx.number(args[4])
    third, redemption = ctx.number(args[5]), ctx.number(args[6])
    frequency = ctx.frequency(args[7])
    basis = ctx.basis(args, 8)
    if not (maturity > first_coupon > settlement > issue) or rate < 0:
        raise ctx.fail()
    if third < 0 or redemption <= 0:
        raise ctx.fail()
    if function == "ODDFYIELD" and third <= 0:
        raise ctx.fail()
    step = 12 // frequency
    settle_d, issue_d = _date_of(settlement, ctx), _date_of(issue, ctx)
    first_d = _date_of(first_coupon, ctx)
    if _Coupons(first_coupon, maturity, frequency, ctx).previous != first_d:  # the first coupon must be one of maturity's coupon dates
        raise ctx.fail()
    to_first = _Coupons(settlement, first_coupon, frequency, ctx)
    e = _coupon_days_in_period(to_first, basis, settle_d)
    n = _Coupons(settlement, maturity, frequency, ctx).count
    m = float(frequency)
    dfc = _nonneg(_numerator_days(issue_d, first_d, basis))
    coupon = 100.0 * rate / m
    if dfc == e:  # an issue date exactly one period before the first coupon is rejected
        raise ctx.fail()
    if dfc < e:
        dsc = _nonneg(_numerator_days(settle_d, first_d, basis))
        accrued_days = _nonneg(_numerator_days(issue_d, settle_d, basis))

        def price_at(yld: float) -> float:
            x = yld / m + 1.0
            y = dsc / e
            total = redemption / x ** (n - 1.0 + y) + coupon * dfc / e / x**y
            for k in range(2, n + 1):
                total += coupon / x ** (k - 1.0 + y)
            return total - accrued_days / e * rate / m * 100.0

    else:
        quasi = _Coupons(issue, first_coupon, frequency, ctx).count
        late = first_d
        dcnl = anl = 0.0
        for index in range(quasi, 0, -1):
            early = _change_month(late, -step, False, ctx)
            nl = _nonneg(float((late - early).days)) if basis == 1 else e
            dci = nl if index > 1 else _nonneg(_numerator_days(issue_d, late, basis))
            begin, end = max(issue_d, early), min(settle_d, late)
            a = _nonneg(_numerator_days(begin, end, basis))
            late = early
            dcnl += dci / nl
            anl += a / nl
        if basis in (2, 3):
            dsc = _nonneg(float((to_first.next - settle_d).days))
        else:
            dsc = e - _numerator_days(to_first.previous, settle_d, basis)
        nq = _quasi_count(first_d, settle_d, step, ctx)
        after_first = _Coupons(first_coupon, maturity, frequency, ctx).count

        def price_at(yld: float) -> float:
            x = yld / m + 1.0
            y = dsc / e
            total = redemption / x ** (y + nq + after_first) + coupon * dcnl / x ** (nq + y)
            for k in range(1, after_first + 1):
                total += coupon / x ** (k + nq + y)
            return total - coupon * anl

    if function == "ODDFPRICE":
        return _out(price_at(third), function)
    return _out(_solve_yield(price_at, third, function, frequency), function)


def _odd_last(function: str, args: list[object], ctx: _Ctx) -> object:
    settlement, maturity, last_interest = (ctx.date(args[i]) for i in range(3))
    rate = ctx.number(args[3])
    third, redemption = ctx.number(args[4]), ctx.number(args[5])
    frequency = ctx.frequency(args[6])
    basis = ctx.basis(args, 7)
    if not (maturity > settlement and settlement > last_interest) or rate < 0:
        raise ctx.fail()
    if third < 0 or redemption <= 0:
        raise ctx.fail()
    if function == "ODDLYIELD" and third <= 0:
        raise ctx.fail()
    step = 12 // frequency
    settle_d, maturity_d, last_d = (_date_of(v, ctx) for v in (settlement, maturity, last_interest))
    count = _Coupons(last_interest, maturity, frequency, ctx).count
    m = float(frequency)
    early = last_d
    dcnl = anl = dscnl = 0.0

    def span(start: date, end: date) -> float:
        if basis == 0:
            return _nonneg(float(_days360_both(start, end)))
        return _nonneg(_numerator_days(start, end, basis))

    for index in range(1, count + 1):
        late = _change_month(early, step, False, ctx)
        nl = span(early, late)
        dci = nl if index < count else span(early, maturity_d)
        if late < settle_d:
            a = dci
        elif early < settle_d:
            a = _nonneg(_numerator_days(early, settle_d, basis))
        else:
            a = 0.0
        begin, end = max(settle_d, early), min(maturity_d, late)
        dsc = _nonneg(_numerator_days(begin, end, basis))
        early = late
        dcnl += dci / nl
        anl += a / nl
        dscnl += dsc / nl
    x = 100.0 * rate / m
    term1 = dcnl * x + redemption
    if function == "ODDLPRICE":
        return _out(term1 / (dscnl * third / m + 1.0) - anl * x, function)
    term2 = anl * x + third
    return _out((term1 - term2) / term2 * (m / dscnl), function)


# ------------------------------------------------------------------------------------------------ entry point


def call(function: str, args: list[object]) -> object:
    try:
        return _dispatch(function, args)
    except (OverflowError, ZeroDivisionError, ValueError) as exc:  # arithmetic that leaves the double range is a DAX error
        raise _fail(function) from exc


def _dispatch(function: str, args: list[object]) -> object:
    ctx = _Ctx(function)
    if function in ("DISC", "INTRATE", "RECEIVED", "PRICEDISC", "YIELDDISC"):
        return _discount_family(function, args, ctx)
    if function in ("TBILLEQ", "TBILLPRICE", "TBILLYIELD"):
        return _tbill(function, args, ctx)
    if function == "ACCRINTM":
        return _accrintm(args, ctx)
    if function in ("PRICEMAT", "YIELDMAT"):
        return _pricemat(function, args, ctx)
    if function.startswith("COUP"):
        return _coupon_function(function, args, ctx)
    if function in ("PRICE", "YIELD", "DURATION", "MDURATION"):
        return _periodic(function, args, ctx)
    if function in ("AMORLINC", "AMORDEGRC"):
        return _amortisation(function, args, ctx)
    if function == "ACCRINT":
        return _accrint(args, ctx)
    if function in ("ODDFPRICE", "ODDFYIELD"):
        return _odd_first(function, args, ctx)
    if function in ("ODDLPRICE", "ODDLYIELD"):
        return _odd_last(function, args, ctx)
    raise KeyError(function)
