"""Date-set functions of DAX time intelligence, measured against Power BI Desktop 2.157.879.0 (iteration 84).

FIRSTDATE / LASTDATE / STARTOF{MONTH,QUARTER,YEAR} / ENDOF{MONTH,QUARTER,YEAR} / NEXT* / PREVIOUS* / DATESYTD,QTD,MTD /
DATESBETWEEN all work on two sets of the dates of one column:

    V  the distinct non-blank dates of the column visible in the current filter context (or the dates of the table the
       function was given)
    U  the distinct non-blank dates of the column over the whole table, every filter ignored

and give a subset of U (the lineage of the column is kept).  The functions here are pure: they take V and U and know nothing
about the evaluator.  No marked date table is needed; any Date / DateTime column works.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

FIRST_LAST = {"FIRSTDATE", "LASTDATE"}
START_END = {f"{edge}OF{unit}" for edge in ("START", "END") for unit in ("MONTH", "QUARTER", "YEAR")}
NEXT_PREVIOUS = {f"{way}{unit}" for way in ("NEXT", "PREVIOUS") for unit in ("DAY", "MONTH", "QUARTER", "YEAR")}
PERIOD_TO_DATE = {"DATESYTD", "DATESQTD", "DATESMTD"}
# the functions this module answers; DATEADD / DATESINPERIOD / PARALLELPERIOD / SAMEPERIODLASTYEAR keep their own code
SET_FUNCTIONS = FIRST_LAST | START_END | NEXT_PREVIOUS | PERIOD_TO_DATE | {"DATESBETWEEN"}
# functions whose last argument is the optional year end
YEAR_END_FUNCTIONS = {"STARTOFYEAR", "ENDOFYEAR", "NEXTYEAR", "PREVIOUSYEAR", "DATESYTD"}
BALANCES = {f"{way}BALANCE{unit}" for way in ("OPENING", "CLOSING") for unit in ("MONTH", "QUARTER", "YEAR")}
DEFAULT_YEAR_END = (12, 31)


class TimeSetError(ValueError):
    """A shape Power BI refuses (the caller turns it into the engine's own error)."""


# --- year end -------------------------------------------------------------------------------------------------------------------

_MONTHS = {
    name.casefold(): number for number, names in enumerate(
        [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
         ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december")], 1)
    for name in names
}


def _two_digit_year(value: int) -> int:
    return 2000 + value if value < 50 else 1900 + value if value < 100 else value


def _valid(month: int, day: int, year: int) -> bool:
    return 1 <= month <= 12 and 1 <= year <= 9999 and 1 <= day <= monthrange(year, month)[1]


def parse_year_end_text(text: str, today: date | None = None) -> tuple[int, int]:
    """The month and day Power BI takes from a year-end string: it is read like an OLE date and only month and day are used."""
    year_now = (today or date.today()).year
    raw = text.strip()
    if not raw:
        raise TimeSetError("Type mismatch.")
    named = re.fullmatch(r"([A-Za-z]+)[\s\-.,/]*(\d{1,2})(?:[\s\-.,/]+(\d{2,4}))?", raw, re.ASCII)
    if named and named.group(1).casefold() in _MONTHS:
        month, day = _MONTHS[named.group(1).casefold()], int(named.group(2))
        if _valid(month, day, year_now if named.group(3) is None else _two_digit_year(int(named.group(3)))):
            return month, day
        raise TimeSetError("Type mismatch.")
    named = re.fullmatch(r"(\d{1,2})[\s\-.,/]*([A-Za-z]+)(?:[\s\-.,/]+(\d{2,4}))?", raw, re.ASCII)
    if named and named.group(2).casefold() in _MONTHS:
        month, day = _MONTHS[named.group(2).casefold()], int(named.group(1))
        if _valid(month, day, year_now if named.group(3) is None else _two_digit_year(int(named.group(3)))):
            return month, day
        raise TimeSetError("Type mismatch.")
    if re.fullmatch(r"\d{1,2}\.\d{1,2}", raw, re.ASCII):
        return 12, 30  # read as a time of day: the date part is 12/30/1899
    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", raw, re.ASCII)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        if _valid(month, day, year):
            return month, day
        raise TimeSetError("Type mismatch.")
    parts = re.fullmatch(r"(\d{1,4})[/\-\s](\d{1,4})(?:[/\-\s](\d{1,4}))?", raw, re.ASCII)
    if parts is None:
        raise TimeSetError("Type mismatch.")
    first, second = int(parts.group(1)), int(parts.group(2))
    if parts.group(3) is not None:
        third = int(parts.group(3))
        year = _two_digit_year(third) if len(parts.group(3)) <= 2 else third
        if _valid(first, second, year):
            return first, second
        if _valid(second, first, year):
            return second, first
        raise TimeSetError("Type mismatch.")
    if len(parts.group(1)) > 2 or len(parts.group(2)) > 2:
        if len(parts.group(1)) > 2 and _valid(second, 1, first):
            return second, 1  # year/month
        raise TimeSetError("Type mismatch.")
    if _valid(first, second, year_now):
        return first, second
    if _valid(second, first, year_now):
        return second, first  # day/month
    if 1 <= first <= 12 and 0 <= second <= 99:
        return first, 1  # month/year
    if 1 <= second <= 12 and 0 <= first <= 99:
        return second, 1  # year/month
    raise TimeSetError("Type mismatch.")


def parse_year_end_value(value: Any, today: date | None = None) -> tuple[int, int]:
    """Year end from an evaluated constant: text, a date serial (number), BLANK."""
    if value is None:
        return DEFAULT_YEAR_END
    if isinstance(value, bool):
        value = Decimal(int(value))
    if isinstance(value, str):
        return parse_year_end_text(value, today)
    if isinstance(value, Decimal):
        if value <= 0:
            return DEFAULT_YEAR_END
        if value >= Decimal(2958466):
            raise TimeSetError("Type mismatch.")
        day = date(1899, 12, 30) + timedelta(days=int(value))
        return day.month, day.day
    raise TimeSetError("Only constant date value is allowed as a year end date argument.")


# --- periods --------------------------------------------------------------------------------------------------------------------


def _year_end_of(year: int, year_end: tuple[int, int]) -> date:
    month, day = year_end
    if (month, day) == (2, 29) and monthrange(year, 2)[1] == 28:
        return date(year, 3, 1)  # a Feb 29 year end rolls over to Mar 1 in a common year (live Power BI)
    return date(year, month, min(day, monthrange(year, month)[1]))


def period_bounds(unit: str, day: date, year_end: tuple[int, int] = DEFAULT_YEAR_END) -> tuple[date, date]:
    """First and last day of the month / quarter / (fiscal) year that holds ``day``; a year at the edge of the date range is cut."""
    if unit == "MONTH":
        return date(day.year, day.month, 1), date(day.year, day.month, monthrange(day.year, day.month)[1])
    if unit == "QUARTER":
        first = ((day.month - 1) // 3) * 3 + 1
        return date(day.year, first, 1), date(day.year, first + 2, monthrange(day.year, first + 2)[1])
    end = _year_end_of(day.year, year_end)
    if day > end:
        if day.year >= date.max.year:
            return end + timedelta(days=1), date.max
        end = _year_end_of(day.year + 1, year_end)
    start = _year_end_of(end.year - 1, year_end) + timedelta(days=1) if end.year > date.min.year else date.min
    return start, end


def neighbour_period(unit: str, day: date, step: int, year_end: tuple[int, int] = DEFAULT_YEAR_END) -> tuple[date, date] | None:
    """The period after (step 1) or before (step -1) the one that holds ``day``; None when it falls outside the date range."""
    start, end = period_bounds(unit, day, year_end)
    try:
        if step > 0:
            if end >= date.max:
                return None
            return period_bounds(unit, end + timedelta(days=1), year_end)
        if start <= date.min:
            return None
        return period_bounds(unit, start - timedelta(days=1), year_end)
    except (OverflowError, ValueError):
        return None


def _unit_of(function: str) -> str:
    for unit in ("MONTH", "QUARTER", "YEAR", "DAY"):
        if function.endswith(unit):
            return unit
    raise TimeSetError(function)


def _between(values: Iterable[date], start: date, end: date) -> list[date]:
    return [value for value in values if start <= value <= end]


def date_set(
    function: str, visible: Iterable[date], universe: Iterable[date], year_end: tuple[int, int] = DEFAULT_YEAR_END,
    bounds: tuple[date | None, date | None] = (None, None),
) -> list[date]:
    """The dates ``function`` selects: a sorted list of distinct members of the universe.

    visible: V, universe: U (both without blanks).  bounds: DATESBETWEEN's start and end (None is BLANK)."""
    seen = sorted(set(visible))
    every = sorted(set(universe))
    if function == "DATESBETWEEN":
        start = every[0] if bounds[0] is None and every else bounds[0]
        end = every[-1] if bounds[1] is None and every else bounds[1]
        if start is None or end is None or start > end:
            return []
        return _between(every, start, end)
    if not seen:
        return []
    if function == "FIRSTDATE":
        return [seen[0]]
    if function == "LASTDATE":
        return [seen[-1]]
    if function in START_END:
        unit = _unit_of(function)
        edge = seen[0] if function.startswith("START") else seen[-1]
        start, end = period_bounds(unit, edge, year_end)
        inside = _between(every, start, end)
        if not inside:
            return []
        return [inside[0]] if function.startswith("START") else [inside[-1]]
    if function in PERIOD_TO_DATE:
        unit = {"DATESYTD": "YEAR", "DATESQTD": "QUARTER", "DATESMTD": "MONTH"}[function]
        last = seen[-1]
        return _between(every, period_bounds(unit, last, year_end)[0], last)
    if function in NEXT_PREVIOUS:
        unit = _unit_of(function)
        forward = function.startswith("NEXT")
        anchor = seen[-1] if forward else seen[0]
        if unit == "DAY":
            try:
                target = anchor + timedelta(days=1 if forward else -1)
            except OverflowError:
                return []
            return [target] if target in set(every) else []
        period = neighbour_period(unit, anchor, 1 if forward else -1, year_end)
        return [] if period is None else _between(every, period[0], period[1])
    raise TimeSetError(function)
