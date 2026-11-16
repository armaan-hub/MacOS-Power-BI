"""Iteration 260: Task 172 dax-hunt-172 (EARLIER / EARLIEST outer row context compile-time validation).

Reject queries at compile time when EARLIER(col[, n]) or EARLIEST(col) has fewer
outer row contexts than required, even in branches that never execute.
"""
import unittest
from decimal import Context, Decimal

from analytics_studio.measures import MeasureError, normalize_calculated_column
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


class Iteration260Hunt172Test(unittest.TestCase):
    def test_earlier_outer_row_context_compile_time_rejections(self) -> None:
        """Reject queries at compile time when EARLIER has fewer outer row contexts than required."""
        reject_cases = [
            # Two problem cases from the brief:
            'IFERROR(MINX(TOPN(0,Facts,Facts[Sales]),EARLIER(Facts[Sales])),"E")',
            'IF(FALSE(),EARLIER(Facts[Sales]),1)',
            # Existing error cases that must stay refused:
            'IFERROR(SUMX(Facts,EARLIER(Facts[Sales])),"E")',
            'IFERROR(EARLIER(Facts[Sales]),"E")',
            'ISERROR(EARLIER(Facts[Sales]))',
            'IFERROR(SUMX(Facts,SUMX(Facts,EARLIER(Facts[Sales],2))),"E")',
            'IFERROR(SUMX(Facts,EARLIER(Facts[Sales],0)),"E")',
            'IFERROR(COUNTROWS(FILTER(Facts,EARLIEST(Facts[Sales])>0)),"E")',
            'IFERROR(SUMX(FILTER(Facts,EARLIER(Facts[Sales])>0),1),"E")',
        ]
        for expr in reject_cases:
            with self.subTest(expr=expr):
                result = dax.local(expr)
                self.assertTrue(
                    result.startswith("LOCAL-REJECT") or result.startswith("PARSER-REJECT"),
                    f"Expected expression to be rejected at compile time, got {result!r} for {expr}",
                )

    def test_earlier_measured_answers_pass(self) -> None:
        """Keep 6 measured answers passing with exact values."""
        passing_cases = [
            ('IFERROR(SUMX(Facts,SUMX(Facts,EARLIER(Facts[Sales]))),"E")', '189'),
            ('IFERROR(SUMX(Facts,COUNTROWS(FILTER(Facts,Facts[Sales]<EARLIER(Facts[Sales])))),"E")', '14'),
            ('IFERROR(SUMX(Facts,SUMX(ADDCOLUMNS(Facts,"x",EARLIER(Facts[Sales])),[x])),"E")', '189'),
            ('IFERROR(SUMX(Facts,SUMX(Facts,SUMX(Facts,EARLIER(Facts[Sales],2)))),"E")', '1134'),
            ('IFERROR(SUMX(Facts,SUMX(Facts,EARLIEST(Facts[Sales]))),"E")', '189'),
            ('IFERROR(MAXX(Facts,MAXX(Facts,EARLIER(Facts[Sales]))),"E")', '20'),
        ]
        for expr, expected in passing_cases:
            with self.subTest(expr=expr):
                result = dax.local(expr)
                self.assertTrue(
                    _same(expected, result),
                    f"Expected {expected}, got {result!r} for {expr}",
                )

    def test_calculated_column_earlier_validation(self) -> None:
        """Calculated column with EARLIER validates with frames=1 (row being computed counts as 1)."""
        # Bare EARLIER at top level has only 1 row context, EARLIER needs at least 2 -> rejected
        with self.assertRaises(MeasureError):
            normalize_calculated_column("Bad1", "EARLIER(Facts[Sales])")

        # EARLIER with n=2 needs at least 3 row contexts -> rejected even with 1 inner frame
        with self.assertRaises(MeasureError):
            normalize_calculated_column(
                "Bad2", "COUNTROWS(FILTER(Facts, Facts[Sales] <= EARLIER(Facts[Sales], 2)))"
            )


if __name__ == "__main__":
    unittest.main()
