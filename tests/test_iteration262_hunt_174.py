"""Iteration 262: Task 174 dax-hunt-174 (BETA.DIST numeric boundaries).

Refuse BETA.DIST where Power BI's numerics at extreme shape parameters are not
modelled by the local engine, and keep the answers that are modelled.
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


class Iteration262Hunt174Test(unittest.TestCase):
    def test_beta_dist_extreme_shapes_refused(self) -> None:
        """Shape parameters that overflow Power BI's numerics at a boundary are refused."""
        refused = [
            "BETA.DIST(0.05,25,1E15,TRUE())",
            "BETA.DIST(0.05,30,1E13,TRUE())",
            "BETA.DIST(0.05,1E15,25,TRUE())",
            "BETA.DIST(0.05,30,3E12,TRUE())",
            "BETA.DIST(0.9,30,1E15,TRUE())",
            "BETA.DIST(1E-15,21,1E15,TRUE())",
        ]
        for expr in refused:
            with self.subTest(expr=expr):
                result = dax.local(expr)
                self.assertTrue(
                    result.startswith("LOCAL-REJECT"),
                    f"Expected {expr} to be refused, got {result!r}",
                )

    def test_beta_dist_measured_answers_pass(self) -> None:
        """Answers that the local engine models exactly are still returned."""
        passing_cases = [
            ("BETA.DIST(0.05,2,1E15,TRUE())", "1"),
            ("BETA.DIST(0.05,2,1E15,FALSE())", "0"),
            ("BETA.DIST(0.05,1E15,2,TRUE())", "0"),
            ("BETA.DIST(0.05,2,1E154,TRUE())", "1"),
            ("BETA.DIST(0.05,11,1E30,TRUE())", "1"),
            ("BETA.DIST(0.05,100,1E11,TRUE())", "1"),
            ("BETA.DIST(0.05,25,1E15,FALSE())", "0"),
        ]
        for expr, expected in passing_cases:
            with self.subTest(expr=expr):
                result = dax.local(expr)
                self.assertTrue(
                    _same(expected, result),
                    f"Expected {expected}, got {result!r} for {expr}",
                )


if __name__ == "__main__":
    unittest.main()
