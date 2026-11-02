"""Task 23 (big-numbers-13): one class per Part, values measured in Power BI Desktop (tools/parity/task23_big_numbers_spec.json).

Each row is (expression, Power BI answer). The local engine must match it (or refuse with LOCAL-REJECT where Power BI gives an error).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class ModQuotientLimitTest(unittest.TestCase):
    """Part F: MOD(x, d) errors when |x / d| >= 1.126E12, works below it."""

    ROWS = [
        ('MOD(1E14,1E10)&"z"', "0z"),
        ("ISERROR(MOD(1E14,2))", "True"),
        ('MOD(1E15,1E10)&"z"', "0z"),
        ('MOD(1E15,888.5)&"z"', "249z"),
        ('MOD(-1E15,888.5)&"z"', "639.5z"),
        ("ISERROR(MOD(2E15,888.5))", "True"),
        ("ISERROR(MOD(1E17,1E4))", "True"),
        ("ISERROR(MOD(CURRENCY(500000000000),0.25))", "True"),
        ("ISERROR(MOD(CURRENCY(200000000000),0.25))", "False"),
        ('MOD(123456789012345.6,1E10)&"z"', "6789012345.59375z"),
        ('MOD(4.5E14+0.3,1E10)&"z"', "0.3125z"),
        ('MOD(1E13+0.7,10)&"z"', "0.69921875z"),
        ('MOD(1099511627776,1)&"z"', "0z"),
        ('MOD(2^49,1E10)&"z"', "9953421312z"),
        ('MOD(2^49+0.5,1E10)&"z"', "9953421312.5z"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class FloorCeilingQuotientHugeTest(unittest.TestCase):
    """Part D: FLOOR, CEILING, QUOTIENT, INT of huge doubles around 2^53 and 2^63."""

    ROWS = [
        ('FLOOR(4.6E18,3)&"z"', "4599999999999989760z"),
        ('CEILING(4.6E18,3)&"z"', "4599999999999989760z"),
        ('FLOOR(4.6E18,7)&"z"', "4599999999999998976z"),
        ('CEILING(4.6E18,7)&"z"', "4599999999999998976z"),
        ('QUOTIENT(4.6E18,3)&"z"', "1533333333333333248z"),
        ('FLOOR(9.2E18,3)&"z"', "9200000000000010240z"),
        ('CEILING(9.2E18,3)&"z"', "9200000000000010240z"),
        ('FLOOR(9.2E18,7)&"z"', "9199999999999970304z"),
        ('CEILING(9.2E18,7)&"z"', "9199999999999970304z"),
        ('QUOTIENT(9.2E18,3)&"z"', "3066666666666666496z"),
        ('FLOOR(9.22337203685477E18,2)&"z"', "9223372036854760448z"),
        ('CEILING(9.22337203685477E18,2)&"z"', "9223372036854760448z"),
        ("ISERROR(FLOOR(9.22337203685477E18,3))", "True"),
        ("ISERROR(CEILING(9.22337203685477E18,3))", "True"),
        ("ISERROR(FLOOR(9.22337203685477E18,7))", "True"),
        ("ISERROR(CEILING(9.22337203685477E18,7))", "True"),
        ('FLOOR(9.22337203685477E18,1024)&"z"', "9223372036854773760z"),
        ('CEILING(9.22337203685477E18,1024)&"z"', "9223372036854773760z"),
        ('FLOOR(9.22337203685477E18,0.5)&"z"', "9.22337203685475E+18z"),
        ('CEILING(9.22337203685477E18,0.5)&"z"', "9.22337203685475E+18z"),
        ('QUOTIENT(9.22337203685477E18,3)&"z"', "3074457345618256384z"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class MroundHugeTest(unittest.TestCase):
    """Part E: MROUND of 1E15..9E15 matches Power BI's double arithmetic."""

    ROWS = [
        ('MROUND(5E15,3)&"z"', "5000000000000002z"),
        ('MROUND(5E15,11)&"z"', "5000000000000006z"),
        ('MROUND(6E15,7)&"z"', "6000000000000000z"),
        ('MROUND(6E15,11)&"z"', "5999999999999996z"),
        ('MROUND(7E15,3)&"z"', "7000000000000002z"),
        ('MROUND(8E15,3)&"z"', "8000000000000002z"),
        ('MROUND(8E15,7)&"z"', "8000000000000002z"),
        ('MROUND(8E15,11)&"z"', "7999999999999998z"),
        ('MROUND(-5E15,-3)&"z"', "-5000000000000002z"),
        ('MROUND(-8E15,-3)&"z"', "-8000000000000002z"),
        ('MROUND(5E15+1,3)&"z"', "5000000000000002z"),
        ('MROUND(5E15+1,11)&"z"', "5000000000000006z"),
        ('MROUND(8E15-1,3)&"z"', "8000000000000002z"),
        ('MROUND(8E15-1,7)&"z"', "8000000000000002z"),
        ('MROUND(8E15-1,11)&"z"', "7999999999999998z"),
        ('MROUND(7.7E15,3)&"z"', "7700000000000002z"),
        ("ISERROR(MROUND(5E15,3))", "False"),
        ("ISERROR(MROUND(8E15,3))", "False"),
        ("ISERROR(MROUND(5E15,-3))", "True"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class ResearchABCTest(unittest.TestCase):
    """Parts A, B, C: EXP, POWER, LN, LOG research rows that match."""

    ROWS = [
        ('EXP(0)&"z"', "1z"),
        ('EXP(1)&"z"', "2.71828182845905z"),
        ('EXP(2)&"z"', "7.38905609893065z"),
        ('POWER(2,0)&"z"', "1z"),
        ('POWER(2,1)&"z"', "2z"),
        ('POWER(2,2)&"z"', "4z"),
        ('POWER(2,-1)&"z"', "0.5z"),
        ('LN(1)&"z"', "0z"),
        ('LOG10(10)&"z"', "1z"),
        ('LOG(8,2)&"z"', "3z"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class FloorCeilingNegativeBeyond2Pow53Test(unittest.TestCase):
    """Fix 1: FLOOR and CEILING of a negative number beyond 2^53 keep the sign (measured)."""

    ROWS = [
        ('FLOOR(-3.3E17,3)&"z"', "-330000000000000000z"),
        ('CEILING(-3.3E17,3)&"z"', "-330000000000000000z"),
        ('FLOOR(-3.3E17,0.25)&"z"', "-3.3E+17z"),
        ('FLOOR(-7.1E18,3)&"z"', "-7100000000000010240z"),
        ('CEILING(-7.1E18,3)&"z"', "-7100000000000010240z"),
        ('FLOOR(-7.1E18,5)&"z"', "-7100000000000000000z"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) != "match"]
        self.assertEqual([], wrong)


class MroundNearTwoPow52Test(unittest.TestCase):
    """Fix 2: MROUND from 2^52 with a whole multiple (measured); an unsettled odd product below 5E15 is refused."""

    ROWS = [
        ('MROUND(4.6E15,3)&"z"', "4600000000000000z"),
        ('MROUND(4.9E15,13)&"z"', "4900000000000002z"),
        ('MROUND(4503599627370497,17)&"z"', "4503599627370498z"),
        ('MROUND(4503599627370497,13)&"z"', "4503599627370493z"),
    ]

    def test_measured_rows_match_or_refuse(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_settled_even_product_matches(self) -> None:
        self.assertEqual("match", status("4503599627370498z", dax.local('MROUND(4503599627370497,3)&"z"')))


class ModDoubleFractionalDivisorTest(unittest.TestCase):
    """Fix 3: MOD of a Double is computed in IEEE doubles (measured)."""

    ROWS = [
        ('MOD(1.0E12*0.1+0.1/3,0.1)&"z"', "3.33349029864394E-02z"),
        ('MOD(1.0E12*13.7+13.7/3,13.7)&"z"', "4.56711679273576z"),
        ('MOD(123456.789,1E-3)&"z"', "1.73740622583241E-12z"),
        ('MOD(-98765.4321,33.3)&"z"', "2.36789999998612z"),
        ('MOD(1E10+0.3,33.3)&"z"', "10.3000000905653z"),
        ('MOD(-1E15,1E4)&"z"', "0z"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) != "match"]
        self.assertEqual([], wrong)
