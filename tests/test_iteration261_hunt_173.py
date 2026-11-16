"""Iteration 261: Task 173 dax-hunt-173 (SWITCH/IF conditions do not affect result type).

A date beside a number in IF/SWITCH branches is a number, also when a skipped
branch has AND(x,"text") in a condition.
"""
import unittest
from decimal import Context, Decimal

from tools import dax_oracle_diff as dax

ROUND15 = Context(prec=15)


def _same(expected: str, local: str) -> bool:
    if expected == "ERR":
        return local.startswith("LOCAL-REJECT") or local.startswith("PARSER-REJECT")
    if local.startswith("LOCAL-"):
        return False
    if expected == local:
        return True
    if expected.lower() in ("true", "false"):
        return expected.lower() == local.lower()
    try:
        want, got = Decimal(expected), Decimal(local)
    except Exception:
        return False
    if not want.is_finite() or not got.is_finite():
        return False
    return ROUND15.plus(want) == ROUND15.plus(got) and want.is_signed() == got.is_signed()


class Iteration261Hunt173Test(unittest.TestCase):
    def test_switch_if_condition_does_not_affect_result_type(self) -> None:
        """SWITCH/IF conditions do not change result type; a date beside a number is a number."""
        cases = [
            # The 2 previously wrong expressions:
            (
                'SWITCH(2,1,0,2,TIME(13,5,0),SWITCH(TRUE(),FALSE(),1,AND(1<2,"a"),2.5,3))',
                "0.545138888888889",
            ),
            (
                'SWITCH(2,1,IF(ISBLANK(0),0,SUM(Facts[Sales])),2,TIME(13,5,0),SWITCH(TRUE(),SUM(Facts[Sales])>0,AVERAGE(Facts[Quantity]),AND((1<2),"a"),2.5,COUNTROWS(Facts)))',
                "0.545138888888889",
            ),
            # The 3 'stays a datetime' cases:
            (
                'IF(TRUE(),TIME(13,5,0),"a")',
                "12/30/1899 13:05:00",
            ),
            (
                'IF(TRUE(),TIME(13,5,0),TRUE())',
                "12/30/1899 13:05:00",
            ),
            (
                'SWITCH(2,1,DATE(2020,1,1),2,TIME(13,5,0))',
                "12/30/1899 13:05:00",
            ),
            # Baseline passing case:
            (
                'SWITCH(2,1,0,2,TIME(13,5,0),SWITCH(TRUE(),FALSE(),1,TRUE(),2.5,3))',
                "0.545138888888889",
            ),
        ]
        for expr, expected in cases:
            with self.subTest(expr=expr):
                result = dax.local(expr)
                self.assertTrue(
                    _same(expected, result),
                    f"Expected {expected}, got {result!r} for {expr}",
                )


if __name__ == "__main__":
    unittest.main()
