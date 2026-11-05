"""SUBSTITUTEWITHINDEX over tied order values: exact invariance over every tie order (Task 59, swi-ties-49).

Power BI numbers rows that the order keys cannot tell apart in its own internal row order, which the local engine does not
know.  The measure evaluator therefore runs the whole expression once for each permutation of the tie groups (every
SUBSTITUTEWITHINDEX tie site gets its own choice) and answers only when every run gives the identical result.  When any run
disagrees, raises, or the search exceeds the limits, the original refusal is kept.

The driver lives in a contextvar so that a SUBSTITUTEWITHINDEX call made outside ``run_with_tie_orders`` still refuses as
before.
"""

from __future__ import annotations

import math
from contextvars import ContextVar
from typing import Any, Callable, TypeVar

TIE_SITE_LIMIT = 720  # the product of the factorials of one site's tie groups
TIE_RUN_LIMIT = 720  # total evaluations of the whole expression across all sites

T = TypeVar("T")

_DRIVER: ContextVar["TieDriver | None"] = ContextVar("swi_tie_driver", default=None)


class TieRefused(Exception):
    """Raised inside the evaluator when the tie order cannot be decided; carries the original refusal text."""


class TieDriver:
    """Tie choices for one run: ``choices[k]`` selects the order at the k-th tie site of the run (default 0 = walk order)."""

    def __init__(self, choices: list[int]) -> None:
        self.choices = list(choices)
        self.radices: list[int] = []  # number of tie orders at each site hit in this run
        self.refusal: str | None = None  # original refusal text of the first tie site hit

    def choose(self, ranked: list[tuple[list[Any], Any]], groups: list[tuple[int, int]], refusal: str) -> list[tuple[list[Any], Any]]:
        """Reorder ``ranked`` inside its tie ``groups`` (start, end) by this run's choice, or raise when it cannot be decided."""
        if self.refusal is None:
            self.refusal = refusal
        sizes = [end - start for start, end in groups]
        total = 1
        for size in sizes:
            total *= math.factorial(size)
        if total > TIE_SITE_LIMIT:
            raise TieRefused(refusal)
        site = len(self.radices)
        self.radices.append(total)
        code = self.choices[site] if site < len(self.choices) else 0
        ordered = list(ranked)
        for (start, end), size in zip(groups, sizes):
            digit, code = code % math.factorial(size), code // math.factorial(size)
            permutation = _nth_permutation(size, digit)
            ordered[start:end] = [ranked[start + p] for p in permutation]
        return ordered


def _nth_permutation(size: int, index: int) -> list[int]:
    """The ``index``-th permutation of range(size) in lexicographic order (factorial number system)."""
    pool = list(range(size))
    result: list[int] = []
    for remaining in range(size, 0, -1):
        position, index = divmod(index, math.factorial(remaining - 1))
        result.append(pool.pop(position))
    return result


def current_driver() -> TieDriver | None:
    """The driver of the run in progress, or None when SUBSTITUTEWITHINDEX is evaluated outside a tie-order search."""
    return _DRIVER.get()


def run_with_tie_orders(run: Callable[[], T], same: Callable[[T, T], bool]) -> T:
    """Evaluate ``run`` under every tie order it reaches; return its result only when all orders agree.

    A run that never reaches a tie site returns at once.  Otherwise the choices are enumerated depth-first over the
    sites seen in each run (at most TIE_RUN_LIMIT runs).  Any error after a tie site was reached, any disagreement, or
    the run limit raises TieRefused with the original refusal text.
    """
    if current_driver() is not None:  # nested call: the outer search already controls the tie orders
        return run()
    choices: list[int] = []
    first: T | None = None
    have_first = False
    runs = 0
    refusal: str | None = None  # the original refusal, once a tie site has been reached
    while True:
        driver = TieDriver(choices)
        token = _DRIVER.set(driver)
        try:
            result = run()
        except Exception as error:
            if driver.refusal is not None:
                raise TieRefused(driver.refusal) from error
            raise
        finally:
            _DRIVER.reset(token)
        runs += 1
        refusal = refusal or driver.refusal
        if refusal is None:
            return result  # no tie site reached: the answer does not depend on tie orders
        if not have_first:
            first, have_first = result, True
        elif not same(first, result):
            raise TieRefused(refusal)
        full = choices + [0] * (len(driver.radices) - len(choices))
        position = len(driver.radices) - 1
        while position >= 0 and full[position] + 1 >= driver.radices[position]:
            position -= 1
        if position < 0:
            return first  # every tie order was run and all agree
        if runs >= TIE_RUN_LIMIT:
            raise TieRefused(refusal)
        choices = full[:position] + [full[position] + 1]
