"""ISONORAFTER: lexicographic "on or after" test over (value, comparand, order) groups, as Power BI Desktop 2.157.879.0.

Compared live through ``tools/dax_battery_order.json``.  BLANK sorts before every value, text ignores case and two
different types raise Power BI's comparison error.
"""

from __future__ import annotations

from decimal import Decimal

from analytics_studio import dax_typed

ARITY: dict[str, tuple[int, int]] = {"ISONORAFTER": (2, 1_000)}
CATEGORY = {"ISONORAFTER": "boolean"}
ORDER_KEYWORDS = {"ASC": True, "DESC": False}
_ORDER_ERROR = (
    "Unexpected value for ORDER argument in ISONORAFTER function. "
    "Use 0/FALSE/DESC for descending order or 1/TRUE/ASC for ascending order."
)


def _ascending(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal) and value in (0, 1):
        return value == 1
    raise dax_typed._error(_ORDER_ERROR)


def _compare(left: object, right: object) -> int:
    """-1, 0 or 1. BLANK sorts as the zero of the other side's type, but strictly below that zero."""
    if left is None and right is None:
        return 0
    if left is None or right is None:
        other = right if left is None else left
        zero = dax_typed._blank_like(other)
        dax_typed.compare("=", other, zero)  # the types must still be comparable
        blank_vs_other = -1 if (dax_typed.compare("=", other, zero) or dax_typed.compare("<", zero, other)) else 1
        return blank_vs_other if left is None else -blank_vs_other
    dax_typed.compare("=", left, right)  # raises the comparison error for mixed types
    if dax_typed.compare("=", left, right):
        return 0
    return 1 if dax_typed.compare(">", left, right) else -1


def call(function: str, args: list[object]) -> object:
    if len(args) % 3 == 1:  # a comparison value with nothing to compare against
        raise dax_typed._error("IsOnOrAfter() function contains a scalar expression to compare without a value to compare against.")
    orders = [_ascending(args[index]) for index in range(2, len(args), 3)]  # every ORDER is checked before any comparison
    for position, index in enumerate(range(0, len(args), 3)):
        ascending = orders[position] if position < len(orders) else True
        order = _compare(args[index], args[index + 1]) * (1 if ascending else -1)
        if order:
            return order > 0
    return True
