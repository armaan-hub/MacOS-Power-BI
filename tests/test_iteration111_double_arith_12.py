"""Task 22 (double-arith-12): one class per Part, values measured in Power BI Desktop 2.157.879.0 (tools/parity/task22_double_arith_spec.json).

Each row is (expression, Power BI answer). The local engine must match it (or refuse with LOCAL-REJECT where Power BI gives an error).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

class Int64WrapTest(unittest.TestCase):
    """Part C: + - * of two Int64 operands wrap at 64 bits; a Double beside them does not."""

    ROWS = [
        ("(9007199254740993*9007199254740993-4.35/1.005)=0.3", "False"),
        ("9007199254740993*9007199254740993", "18014398509481985"),
        ("ISERROR(9007199254740993*9007199254740993)", "False"),
        ("(9223372036854775807+1)&\"z\"", "-9223372036854775808z"),
        ("9223372036854775807*2", "-2"),
        ("ISERROR(9223372036854775807*2)", "False"),
        ("(-9223372036854775807-2)&\"z\"", "9223372036854775807z"),
        ("3037000500*3037000500", "-9223372036709301616"),
        ("ISERROR(3037000500*3037000500)", "False"),
        ("(4294967296*4294967296)&\"z\"", "0z"),
        ("9223372036854775807+1.0", "9.22337203685478E+18"),
        ("ISERROR(9223372036854775807+1.0)", "False"),
        ("(9223372036854775807+0.5)&\"z\"", "9.22337203685478E+18z"),
        ("MAX(Facts[Quantity])*9223372036854775807", "9223372036854775803"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class IntegerRangeTest(unittest.TestCase):
    """Part D: INT, FLOOR, CEILING, QUOTIENT, MROUND and CONVERT to an Integer beyond the 64-bit range are the conversion error; a Double is read by its 15 digits."""

    ROWS = [
        ("INT((EXP(1)*0.2)*1E15)", "543656365691809"),
        ("INT((DIVIDE(1,3)*1.1)*1E15)", "366666666666667"),
        ("INT((2.675+9007199254740993)*1E15)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"The result of a conversion or arithmetic operation is either too large or too small.\""),
        ("INT((PI()*PI())*1E15)", "9869604401089358"),
        ("INT((0.2-SUM(Facts[Quantity]))*1E15)", "-14800000000000000"),
        ("INT((SUM(Facts[Sales])*0.1/MAX(Facts[Sales])/7)*1E15)", "22500000000000"),
        ("INT((0.2-1E16)*1E15)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"The result of a conversion or arithmetic operation is either too large or too small.\""),
        ("INT((0.1*100.1*0.1)*1E15)", "1001000000000000"),
        ("INT((SUM(Facts[Sales])*0.1-SUM(Facts[Quantity]))*1E15)", "-11850000000000000"),
        ("INT((0.3+0.1)*1E15)", "400000000000000"),
        ("INT((123456.789/SQRT(2))*1E15)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"The result of a conversion or arithmetic operation is either too large or too small.\""),
        ("INT(9.3E18)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"The result of a conversion or arithmetic operation is either too large or too small.\""),
        ("ISERROR(INT(1E19))", "True"),
        ("FLOOR(1E16+0.5,1)", "10000000000000000"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class RoundHugeTest(unittest.TestCase):
    """Part E: ROUND, ROUNDUP, ROUNDDOWN, TRUNC and EVEN of a finite value beyond 1E16 return the value; TRUNC and ROUNDDOWN of +Infinity are NaN."""

    ROWS = [
        ("ROUND(1E-7-0.1+0.2/1E308+123456.789-0.7,14)", "123455.9890001"),
        ("ROUND(1E308/\"0.1\"/0.3,14)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"Query (1, 19) An argument of function 'ROUND' has the wrong data type or the result is too large or too small.\""),
        ("ROUND(1E308+1.005,14)", "1E+308"),
        ("ROUND(PI()/EXP(1)-PI()-1E308/100,14)", "-1E+306"),
        ("ROUND(0.1+0.2+1E308-1.005,14)", "1E+308"),
        ("ROUND(EXP(1)+SQRT(2)+1E308+AVERAGE(Facts[Quantity]),14)", "1E+308"),
        ("ROUND(1E308*10,14)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"Query (1, 19) An argument of function 'ROUND' has the wrong data type or the result is too large or too small.\""),
        ("ROUND(1E308+100,14)", "1E+308"),
        ("ROUND(9007199254740993/1E-7*1E308,14)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"Query (1, 19) An argument of function 'ROUND' has the wrong data type or the result is too large or too small.\""),
        ("ROUND(1E308*5E-324-LN(10)/1.005*4.35,14)", "-9.96641308907871"),
        ("ROUND(1E308/MAX(Facts[Sales])/7,14)", "7.14285714285714E+305"),
        ("ROUND(1E300,14)", "1E+300"),
        ("ROUNDDOWN(1E300,0)", "1E+300"),
        ("ROUND(-1E300,0)", "-1E+300"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class OverflowUnderflowTest(unittest.TestCase):
    """Part F: arithmetic past the Double range is Infinity; below it rounds to the nearest double."""

    ROWS = [
        ("ROUND(SUM(Facts[Sales])*0.1-100.1+0.1+0.2*9007199254740993-5E-324,14)", "1.8014398509481E+15"),
        ("(5E-324*\"0.1\"*SUM(Facts[Sales])*0.1)&\"z\"", "0z"),
        ("CONCATENATEX({1},0.1+0.2+1E308)", "1E+308"),
        ("INT((2^-0.5/5E-324)*1E15)", "0"),
        ("ROUND(2^-0.5-1000*5E-324,14)", "0.70710678118655"),
        ("ISDOUBLE(1E308*PI())", "True"),
        ("FORMAT(0.2-1E308,\"0.000000000000000000\")", "-100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000.000000000000000000"),
        ("(1E308/2/3)&\"z\"", "1.66666666666667E+307z"),
        ("INT((5E-324+123456.789)*1E15)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"The result of a conversion or arithmetic operation is either too large or too small.\""),
        ("CONCATENATEX({1},2^-0.5/1E308)", "1"),
        ("(5E-324-PI())=0.3", "False"),
        ("FORMAT(5E-324/LN(10),\"0.000000000000000000\")", "0.000000000000000000"),
        ("ISDOUBLE(5E-324*SUM(Facts[Sales])*0.1)", "True"),
        ("CONCATENATEX({1},2^-0.5/3/5E-324)", "0"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class IteratorDoubleSumTest(unittest.TestCase):
    """Part B: SUMX and AVERAGEX of a Double body add in doubles, in row order (a constant body is counted)."""

    ROWS = [
        ("SUMX({1,2},2^-0.5/2.675*1.0000000000000002*1E15+0.3)", "0.6"),
        ("SUMX({1,2},100.1+123456.789)", "247113.778"),
        ("SUMX({1,2},1.005+100.1)", "202.21"),
        ("SUMX({1,2},AVERAGE(Facts[Quantity])+AVERAGE(Facts[Quantity])+7)", "24"),
        ("SUMX({1,2},LN(10)*1)", "4.60517018598809"),
        ("SUMX({1,2},1E-7*SQRT(2)-100.1/SQRT(2))", "-141.562777310704"),
        ("SUMX({1,2},AVERAGE(Facts[Quantity])*0.3)", "1.5"),
        ("SUMX({1,2},MAX(Facts[Sales])/7/100)", "0.0571428571428571"),
        ("SUMX({1,2},2^-0.5/MAX(Facts[Sales])/7)", "1.99505507188377"),
        ("SUMX({1,2},9007199254740993/4.35-1E15+0.3)", "2.14124103666253E+15"),
        ("SUMX({1,2},DIVIDE(1,3)+COUNTROWS(Facts))", "12.6666666666667"),
        ("SUMX({1,2},SUM(Facts[Sales])*0.1-SQRT(2)-1.0000000000000002)", "1.47157287525381"),
        ("SUMX({1,2},1E-7/1000*\"0.1\"-100/9007199254740993)", "1.99777955395075E-11"),
        ("(SUMX(Facts,Facts[Sales]*0.1)-SUM(Facts[Sales])*0.1)&\"z\"", "-4.44089209850063E-16z"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class DoubleArithmeticTest(unittest.TestCase):
    """Part A: Double + - * / are computed in IEEE doubles and the result keeps its exact binary value."""

    ROWS = [
        ("(LN(10)+1000)=0.3", "False"),
        ("(MAX(Facts[Sales])/7+EXP(1))&\"z\"", "5.5754246856019z"),
        ("ROUND(0.1*2/3,14)", "0.06666666666667"),
        ("ISDOUBLE(0.1/1/3)", "True"),
        ("ISDOUBLE(1E-7-1.0000000000000002*EXP(1))", "True"),
        ("ROUND(123456.789-PI(),14)", "123453.647407346"),
        ("ISDOUBLE(SUM(Facts[Sales])*0.1*COUNTROWS(Facts))", "True"),
        ("ROUND(MAX(Facts[Sales])/7+\"0.1\",14)", "2.95714285714286"),
        ("ISDOUBLE(1.005+2.675)", "True"),
        ("CONCATENATEX({1},AVERAGE(Facts[Quantity])*4.35)", "10.875"),
        ("(2/3*0.7+1E15+0.3)&\"z\"", "1E+15z"),
        ("CONCATENATEX({1},0.3+SQRT(2)-2^-0.5)", "1.00710678118655"),
        ("CONCATENATEX({1},0.2*\"0.1\")", "0.02"),
        ("FORMAT(MAX(Facts[Sales])/10*0.1,\"0.00000000000000000000\")", "0.20000000000000000000"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


class ReviewFixTest(unittest.TestCase):
    """Review fixes (fresh Power BI answers on three Facts tables): ODD beyond 1E16, SUMX of a constant, FLOOR/CEILING/QUOTIENT/CONVERT of a big Double, MOD/MROUND, ABS and SUMX Int64 overflow, text just under 1E15."""

    ROWS = [
        ("(ODD(9.22E18))&\"z\"", "9.22E+18z"),
        ("(ODD(1E17+0.5))&\"z\"", "1E+17z"),
        ("(ODD(1.1E16))&\"z\"", "1.1E+16z"),
        ("(SUMX({1,2,3,4,5,6,7},0.1)-COUNTROWS({1,2,3,4,5,6,7})*0.1)&\"z\"", "-1.11022302462516E-16z"),
        ("(SUMX({1,2,3,4,5,6,7},0.7)-COUNTROWS({1,2,3,4,5,6,7})*0.7)&\"z\"", "8.88178419700125E-16z"),
        ("(SUMX(FILTER(Facts,Facts[Quantity]>1),0.1)-COUNTROWS(FILTER(Facts,Facts[Quantity]>1))*0.1)&\"z\"", "0z"),
        ("(SUMX(VALUES(Facts[Region]),0.7)-COUNTROWS(VALUES(Facts[Region]))*0.7)&\"z\"", "0z"),
        ("(FLOOR(9.2233720368547E18,1))&\"z\"", "9223372036854700032z"),
        ("(CEILING(9.2233720368547E18,1))&\"z\"", "9223372036854700032z"),
        ("(QUOTIENT(9.2233720368547E18,1))&\"z\"", "9223372036854700032z"),
        ("(CONVERT(9.2233720368547E18,INTEGER))&\"z\"", "9223372036854700032z"),
        ("(CONVERT(4.5E15+0.5,INTEGER))&\"z\"", "4500000000000001z"),
        ("(CEILING(4.5E15+0.5,1))&\"z\"", "4500000000000000z"),
        ("ISERROR(MOD(5E15,3))", "True"),
        ("ISERROR(MOD(4.5E15+0.5,3))", "True"),
        ("(MROUND(1.1E16,3))&\"z\"", "11000000000000000z"),
        ("(MROUND(9.9E15+0.5,3))&\"z\"", "9900000000000000z"),
        ("ISERROR(ABS(9223372036854775807+1))", "True"),
        ("(SUMX({9223372036854775807,1},[Value]))&\"z\"", "-9223372036854775808z"),
        ("(0.1-1E15)&\"z\"", "-1000000000000000z"),
        ("(1E15-0.3)&\"z\"", "1000000000000000z"),
        # round 2 (fresh answers R2)
        ("ISERROR(MOD(1E15,3))", "True"),
        ("ISERROR(MOD(-5E15,3))", "True"),
        ("ISERROR(MOD(2E15,0.5))", "True"),
        ("(MROUND(1E15,3))&\"z\"", "999999999999999z"),
        ("(MROUND(4E15,3))&\"z\"", "3999999999999999z"),
        ("ISERROR(ABS(-9223372036854775807))", "True"),
        ("ISERROR(ABS(9223372036854775807+2))", "True"),
        ("(-(9223372036854775807+1))&\"z\"", "-9223372036854775808z"),
        ("(AVERAGEX({9223372036854775807,1},[Value]))&\"z\"", "-4.61168601842739E+18z"),
        ("(AVERAGEX(ADDCOLUMNS(Facts,\"k\",1),1.3)-1.3)&\"z\"", "0z"),
        ("(AVERAGEX(ADDCOLUMNS(Facts,\"k\",1),0.1)-0.1)&\"z\"", "-1.38777878078145E-17z"),
        ("(SUMX(ADDCOLUMNS(Facts,\"k\",1),0.7)-COUNTROWS(ADDCOLUMNS(Facts,\"k\",1))*0.7)&\"z\"", "8.88178419700125E-16z"),
    ]

    def test_power_beyond_1e15_is_refused(self) -> None:
        for expr in ("(INT(2^52+0.5))&\"z\"", "(QUOTIENT(2^52+0.5,1))&\"z\"", "(CONVERT(2^52+0.5,INTEGER))&\"z\""):
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)
        # Task 38 (2026-11-03): from 2^53 up a power is its exact double; Power BI Desktop measured 9007199254740990z on 2026-11-03
        self.assertEqual("9007199254740990z", dax.local("(FLOOR(2^53+0.5,1))&\"z\""))

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)

    def test_no_row_is_refused_wrongly(self) -> None:
        refused = [expr for expr, want in self.ROWS if status(want, dax.local(expr)) == "gap-reject"]
        self.assertEqual([], refused)


if __name__ == "__main__":
    unittest.main()
