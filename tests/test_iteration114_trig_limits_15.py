"""Task 25 (trig-limits-15): tests for Part B (BLANK date arithmetic) and Part D (trigonometric limits).

Measured in Power BI Desktop (tools/parity/task25_trig_blank_date_spec.json).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class BlankDateArithmeticTest(unittest.TestCase):
    """Part B: a BLANK date from an empty-table MAXX/MINX plus or minus a number stays a date."""

    ROWS = [
        ('MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1&""', "12/31/1899"),
        ("ISBLANK(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1)", "False"),
        ('FORMAT(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1,"yyyy-mm-dd hh:nn")', "1899-12-31 00:00"),
        ('MINX(FILTER(Facts,FALSE()),DATE(2020,1,1))-1&""', "12/29/1899"),
        ("ISBLANK(MINX(FILTER(Facts,FALSE()),DATE(2020,1,1))-1)", "False"),
        ('FORMAT(MINX(FILTER(Facts,FALSE()),DATE(2020,1,1))-1,"yyyy-mm-dd hh:nn")', "1899-12-29 00:00"),
        ('MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))*1&""', ""),
        ("ISBLANK(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))*1)", "True"),
        ('MAXX(FILTER(Facts,FALSE()),NOW())+0.5&""', "12:00:00 PM"),
        ("ISBLANK(MAXX(FILTER(Facts,FALSE()),NOW())+0.5)", "False"),
        ('FORMAT(MAXX(FILTER(Facts,FALSE()),NOW())+0.5,"yyyy-mm-dd hh:nn")', "1899-12-30 12:00"),
        ('MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+TIME(1,0,0)&""', "1:00:00 AM"),
        ("ISBLANK(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+TIME(1,0,0))", "False"),
        ('SUMX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1&""', "12/31/1899"),
        ('(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1)&"z"&""', "12/31/1899z"),
        ('INT(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1)&""', "1"),
        ('YEAR(MAXX(FILTER(Facts,FALSE()),DATE(2020,1,1))+1)&""', "1899"),
    ]

    def test_blank_date_arithmetic_matches_power_bi(self) -> None:
        wrong = [(expr, want, dax.local(expr)) for expr, want in self.ROWS if status(want, dax.local(expr)) != "match"]
        self.assertEqual([], wrong)


class TrigLimitsTest(unittest.TestCase):
    """Part D: SIN, COS, TAN, COT limit at |x| >= 2^27 (134217728), ASINH overflow at 1E300."""

    ROWS = [
        # Exactly at 2^27 (134217728) and above: error
        ("ISERROR(SIN(134217728))", "True"),
        ("ISERROR(COS(134217728))", "True"),
        ("ISERROR(TAN(134217728))", "True"),
        ("ISERROR(COT(134217728))", "True"),
        ("ISERROR(SIN(134217728.5))", "True"),
        ("ISERROR(COS(134217728.5))", "True"),
        ("ISERROR(TAN(134217728.5))", "True"),
        ("ISERROR(SIN(-134217728))", "True"),
        ("ISERROR(COS(-134217728))", "True"),
        ("ISERROR(TAN(-134217728))", "True"),
        ("ISERROR(SIN(134217729))", "True"),
        ("ISERROR(COS(134217729))", "True"),
        ("ISERROR(TAN(134217729))", "True"),
        ("ISERROR(SIN(1E10))", "True"),
        ("ISERROR(COS(1E10))", "True"),
        ("ISERROR(TAN(1E10))", "True"),
        ("ISERROR(SIN(1E15))", "True"),
        ("ISERROR(COS(1E15))", "True"),
        ("ISERROR(TAN(1E15))", "True"),
        # Just below 2^27: works
        ("ISERROR(SIN(134217727))", "False"),
        ("ISERROR(COS(134217727))", "False"),
        ("ISERROR(TAN(134217727))", "False"),
        ("ISERROR(COT(134217727))", "False"),
        # ASINH overflow
        ("ISERROR(ASINH(134217728))", "False"),
        ("ISERROR(ASINH(1E9))", "False"),
        ("ISERROR(ASINH(1E300))", "True"),
        # ACOSH overflow (value squared) measured live 2026-11-03
        ("ISERROR(ASINH(1E154))", "False"),
        ("ISERROR(ASINH(1.4E154))", "True"),
        ("ISERROR(ACOSH(1E154))", "False"),
        ("ISERROR(ACOSH(1.3E154))", "False"),
        ("ISERROR(ACOSH(1.35E154))", "True"),
        ("ISERROR(ACOSH(1.4E154))", "True"),
        ("ISERROR(ACOSH(1E200))", "True"),
        ("ISERROR(ACOSH(1E308))", "True"),
        # Hyperbolic / other trig at 134217728
        ("ISERROR(SINH(134217728))", "True"),
        ("ISERROR(COSH(134217728))", "True"),
        ("ISERROR(TANH(134217728))", "False"),
        ("ISERROR(ATAN(134217728))", "False"),
        ("ISERROR(DEGREES(134217728))", "False"),
        ("ISERROR(RADIANS(134217728))", "False"),
    ]

    def test_trig_limits_match_power_bi(self) -> None:
        wrong = [(expr, want, dax.local(expr)) for expr, want in self.ROWS if status(want, dax.local(expr)) != "match"]
        self.assertEqual([], wrong)


if __name__ == "__main__":
    unittest.main()
