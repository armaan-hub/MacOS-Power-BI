"""Power BI-verified answers for the bit, cotangent, string-search, path, NETWORKDAYS, YEARFRAC and type-test functions.

Every expected value below is the answer Power BI Desktop 2.157.879.0 gave (``tools/parity/dax_battery_misc.json`` holds
the full saved set; this file keeps representative cases per function).  ``ERR`` means Power BI raises an error.
"""

from __future__ import annotations

from decimal import Decimal
import unittest

from analytics_studio import dax_ext, dax_misc
from analytics_studio.measures import MeasureError, evaluate_measures

ERR = "ERR"
BLANK = None


class Text(str):
    """An expected text result that happens to look like a number."""


def evaluate(expression: str) -> object:
    return evaluate_measures(
        [{"name": "M", "expression": expression}], [{"A": "1"}], ["A"], "T", measure_names=["M"]
    )["M"]


class DaxMiscTests(unittest.TestCase):
    def check(self, cases: list[tuple[str, object]]) -> None:
        for expression, expected in cases:
            with self.subTest(expression=expression):
                if expected == ERR:
                    with self.assertRaises(MeasureError):
                        evaluate(expression)
                    continue
                value = evaluate(expression)
                if isinstance(expected, bool) or expected is None or isinstance(expected, Text) or (
                    isinstance(expected, str) and not isinstance(value, Decimal)
                ):
                    self.assertEqual(value, None if expected is None else (bool(expected) if isinstance(expected, bool) else str(expected)))
                    self.assertIs(type(value), type(expected) if not isinstance(expected, Text) else str)
                else:
                    self.assertIsInstance(value, Decimal)
                    expected_number = Decimal(str(expected))
                    self.assertLessEqual(
                        abs(value - expected_number), Decimal("1e-9") * max(Decimal(1), abs(expected_number))
                    )

    def test_registered_with_the_function_registry(self) -> None:
        for name in dax_misc.ARITY:
            self.assertIn(name, dax_ext.ARITY)
        for unsupported in ("ISINTEGER", "ISINT64", "ISDOUBLE", "ISDECIMAL", "ISCURRENCY", "NAMEOF", "PATH"):
            self.assertNotIn(unsupported, dax_misc.ARITY)

    def test_bit_functions(self) -> None:
        self.check([
            ("BITAND(12,10)", 8), ("BITOR(12,10)", 14), ("BITXOR(12,10)", 6), ("BITAND(-1,5)", 5),
            ("BITOR(-1,5)", -1), ("BITXOR(-1,5)", -6), ("BITAND(-5,-3)", -7), ("BITXOR(-5,-3)", 6),
            ("BITAND(5.7,3)", 2), ("BITAND(5,3.6)", 4), ("BITAND(5.5,3.5)", 4), ("BITOR(-2.5,0)", -3),
            ("BITAND(BLANK(),5)", BLANK), ("BITAND(5,BLANK())", BLANK), ("BITOR(BLANK(),5)", 5),
            ("BITXOR(5,BLANK())", 5), ("BITOR(BLANK(),BLANK())", BLANK), ("BITXOR(BLANK(),BLANK())", BLANK),
            ('BITAND("12",10)', 8), ("BITAND(TRUE(),1)", 1), ("BITXOR(TRUE(),1)", 0), ('BITAND("abc",1)', ERR),
            ('BITOR("",1)', ERR), ("BITAND(9223372036854775807,1)", 1), ("BITOR(9223372036854775807,1)", 9223372036854775807),
            ("BITAND(9223372036854775808,1)", ERR), ("BITAND(-9223372036854775808,1)", ERR), ("BITAND(1E+20,1)", ERR),
            ("BITAND(1/0,1)", ERR), ("BITAND(9223372036854775807.4,1)", ERR),
            ("BITAND(281474976710656,1)", 0), ("BITOR(281474976710656,1)", 281474976710657),
            ("BITAND(1)", ERR), ("BITAND(1,2,3)", ERR),
            ("BITLSHIFT(1,10)", 1024), ("BITLSHIFT(1,63)", -9223372036854775808), ("BITLSHIFT(1,64)", 1),
            ("BITLSHIFT(1,100)", 68719476736), ("BITLSHIFT(1,-1)", 0), ("BITLSHIFT(-1,-1)", -1), ("BITLSHIFT(8,-1)", 4),
            ("BITLSHIFT(5.5,1)", 12), ("BITLSHIFT(5,1.5)", 20), ("BITLSHIFT(BLANK(),1)", BLANK), ("BITLSHIFT(5,BLANK())", 5),
            ("BITLSHIFT(9223372036854775807,1)", -2), ("BITLSHIFT(-5,60)", -5764607523034234880),
            ("BITLSHIFT(1,-64)", 1), ("BITLSHIFT(1,-65)", 0), ("BITLSHIFT(1,129)", 2),
            ("BITLSHIFT(1,9223372036854775807)", -9223372036854775808), ("BITLSHIFT(1,9223372036854775808)", ERR),
            ("BITRSHIFT(16,2)", 4), ("BITRSHIFT(-5,1)", -3), ("BITRSHIFT(-1,64)", -1), ("BITRSHIFT(1,-1)", 2),
            ("BITRSHIFT(1,-63)", -9223372036854775808), ("BITRSHIFT(-16,-2)", -64), ("BITRSHIFT(BLANK(),BLANK())", BLANK),
            ("BITRSHIFT(1,64)", 1), ("BITRSHIFT(256,129)", 128), ('BITRSHIFT("3",1)', 1), ("BITRSHIFT(1)", ERR),
        ])

    def test_cotangents(self) -> None:
        self.check([
            ("COT(1)", "0.642092615934331"), ("COT(-1)", "-0.642092615934331"), ("COT(2)", "-0.457657554360286"),
            ("COT(100)", "-1.70295691942647"), ("COT(0.0001)", "9999.99996666667"), ("COT(1E-300)", "1E+300"),
            ("COT(0)", ERR), ("COT(BLANK())", ERR), ("COT(FALSE())", ERR), ("COT(TRUE())", "0.642092615934331"),
            ('COT("2")', "-0.457657554360286"), ('COT("abc")', ERR), ("COT(1/0)", ERR), ("COT(1E+10)", ERR),
            ("COT(134217728)", ERR), ("COT(-134217728)", ERR), ("COT(134217726.5)", "1.02505347955482"),
            ("COT(1E+6)", "-2.6764843400545"), ("COT(3.14159265358979)", "-321685687669321"),
            ("COT(1E-308)", ERR), ("COT(2.2250738585072014E-308)", "4.49423283715579E+307"),
            # the engine's wrong octant at exact multiples of pi/4
            ("COT(PI())", 1), ("COT(-PI())", -1), ("COT(PI()*3)", 1), ("COT(PI()/2)", ERR), ("COT(PI()/4)", ERR),
            ("COT(2*PI())", ERR), ("COT(3*PI()/4)", ERR), ("COT(PI()/3)", "0.577350269189626"),
            ("COT()", ERR), ("COT(1,2)", ERR),
            ("COTH(1)", "1.31303528549933"), ("COTH(-1)", "-1.31303528549933"), ("COTH(0.5)", "2.16395341373865"),
            ("COTH(10)", "1.00000000412231"), ("COTH(100)", 1), ("COTH(1E+300)", 1), ("COTH(0)", ERR),
            ("COTH(BLANK())", ERR), ("COTH(1/0)", 0), ("COTH(-1/0)", 0), ("COTH(0/0)", 0), ("COTH(1E-300)", "1E+300"),
            ("COTH(2.2E-308)", ERR), ('COTH("2")', "1.03731472072755"),
            ("ACOT(1)", "0.785398163397448"), ("ACOT(-1)", "2.35619449019234"), ("ACOT(0)", "1.5707963267949"),
            ("ACOT(100)", "0.00999966668666524"), ("ACOT(-100)", "3.13159298690313"), ("ACOT(1E+300)", "1E-300"),
            ("ACOT(-1E+300)", "3.14159265358979"), ("ACOT(BLANK())", "1.5707963267949"), ("ACOT(1/0)", 0),
            ("ACOT(-1/0)", "3.14159265358979"), ("ACOT(0/0)", "3.14159265358979"), ("ACOT(2.2E-308)", 0),
            ("ACOT(1E-307)", "1.5707963267949"), ("ACOT(TRUE())", "0.785398163397448"),
            ("ACOTH(2)", "0.549306144334055"), ("ACOTH(-2)", "-0.549306144334055"), ("ACOTH(1.0001)", "4.95176877564314"),
            ("ACOTH(1.00000001)", "9.55691396779489"), ("ACOTH(1E+300)", "1E-300"), ("ACOTH(1)", ERR),
            ("ACOTH(-1)", ERR), ("ACOTH(0.5)", ERR), ("ACOTH(0)", ERR), ("ACOTH(BLANK())", ERR), ("ACOTH(1/0)", 0),
            ("ACOTH(0/0)", 0), ('ACOTH("abc")', ERR), ("ACOTH(1,2)", ERR),
        ])

    def test_containsstring(self) -> None:
        self.check([
            ('CONTAINSSTRING("Hello World","world")', True), ('CONTAINSSTRING("Hello World","xyz")', False),
            ('CONTAINSSTRING("Hello","")', True), ('CONTAINSSTRING("","")', False), ('CONTAINSSTRING("","a")', False),
            ('CONTAINSSTRING(BLANK(),"a")', False), ('CONTAINSSTRING("a",BLANK())', True),
            ("CONTAINSSTRING(BLANK(),BLANK())", False), ('CONTAINSSTRING("",BLANK())', False),
            ('CONTAINSSTRING("ÄBC","äbc")', True), ('CONTAINSSTRING("straße","STRASSE")', True),
            ('CONTAINSSTRING("İstanbul","istanbul")', False), ('CONTAINSSTRING("ǅ","ǆ")', True),
            ('CONTAINSSTRING("résumé","RESUME")', False), ('CONTAINSSTRING("Ａ","a")', True),
            ('CONTAINSSTRING("あ","ア")', True), ('CONTAINSSTRING("ﬁ","fi")', True), ('CONTAINSSTRING("æ","AE")', True),
            ('CONTAINSSTRING("a­b","ab")', True), ('CONTAINSSTRING("a​b","ab")', False),
            ("CONTAINSSTRING(12345,23)", True), ("CONTAINSSTRING(TRUE(),\"ru\")", True),
            ('CONTAINSSTRING(DATE(2020,1,15),"1/15")', True), ('CONTAINSSTRING("abc",2)', False),
            ('CONTAINSSTRING("abc","a*c")', True), ('CONTAINSSTRING("abc","a?c")', True), ('CONTAINSSTRING("abc","a%")', False),
            ('CONTAINSSTRING("a*c","a~*c")', True), ('CONTAINSSTRING("abc","a~*c")', False), ('CONTAINSSTRING("a~b","~")', True),
            ('CONTAINSSTRING("a")', ERR), ('CONTAINSSTRING("a","b","c")', ERR),
            ('CONTAINSSTRINGEXACT("Hello World","world")', False), ('CONTAINSSTRINGEXACT("Hello World","World")', True),
            ('CONTAINSSTRINGEXACT("","")', True), ('CONTAINSSTRINGEXACT(BLANK(),BLANK())', True),
            ('CONTAINSSTRINGEXACT(BLANK(),"a")', False), ('CONTAINSSTRINGEXACT("a",BLANK())', True),
            ('CONTAINSSTRINGEXACT("abc","a*c")', False), ('CONTAINSSTRINGEXACT("a*c","*")', True),
            ('CONTAINSSTRINGEXACT("straße","ß")', True), ('CONTAINSSTRINGEXACT("ss","ß")', True),
            ('CONTAINSSTRINGEXACT("ß","ss")', False), ('CONTAINSSTRINGEXACT("ae","æ")', True),
            ('CONTAINSSTRINGEXACT("Ａ","a")', False), ('CONTAINSSTRINGEXACT("a­b","ab")', True),
            ('CONTAINSSTRINGEXACT("ab","a­b")', False), ('CONTAINSSTRINGEXACT("é","é")', True),
            ('CONTAINSSTRINGEXACT("é","é")', False), ("CONTAINSSTRINGEXACT(TRUE(),\"ru\")", False),
            ("CONTAINSSTRINGEXACT(TRUE(),\"RU\")", True), ('CONTAINSSTRINGEXACT(1E+20,"E")', True),
        ])

    def test_paths(self) -> None:
        self.check([
            ('PATHLENGTH("1|2|3")', 3), ('PATHLENGTH("")', 1), ("PATHLENGTH(BLANK())", BLANK), ('PATHLENGTH("|")', 2),
            ('PATHLENGTH("a||b||c")', 5), ("PATHLENGTH(123)", 1), ('PATHLENGTH(" 1 | 2 ")', 2), ("PATHLENGTH()", ERR),
            ('PATHITEM("a|b|c",1)', "a"), ('PATHITEM("a|b|c",3)', "c"), ('PATHITEM("a|b|c",0)', BLANK),
            ('PATHITEM("a|b|c",4)', BLANK), ('PATHITEM("a|b|c",-1)', BLANK), ('PATHITEM("a|b|c",1.5)', "b"),
            ('PATHITEM("a|b|c",1.4)', "a"), ('PATHITEM("a|b|c",BLANK())', BLANK), ('PATHITEM("a|b|c","2")', "b"),
            ('PATHITEM("a|b|c","x")', ERR), ('PATHITEM("",1)', ""), ("PATHITEM(BLANK(),1)", BLANK),
            ('PATHITEM(BLANK(),"x")', ERR), ('PATHITEM("1||3",2)', ""), ('PATHITEM("|1|2",1)', ""), ('PATHITEM(" 1 | 2 ",1)', " 1 "),
            ('PATHITEM("a|b|c",TRUE())', "a"), ('PATHITEM("a|b|c",1/0)', ERR), ('PATHITEM("a|b|c",9223372036854775807)', BLANK),
            ('PATHITEM("a|b|c",9223372036854775808)', ERR), ("PATHITEM(TRUE(),1)", "TRUE"), ("PATHITEM(1.5,1)", Text("1.5")),
            ('PATHITEM("1|2|3",2,0)', Text("2")), ('PATHITEM("1|2|3",2,1)', 2), ('PATHITEM("1|2|3",2,2)', ERR),
            ('PATHITEM("1|2|3",2,BLANK())', ERR), ('PATHITEM("1|2|3",2,"1")', ERR), ('PATHITEM("1|2|3",2,TRUE())', ERR),
            ('PATHITEM("1|2|3",2,1.5)', ERR), ('PATHITEM("a|b",1,1)', ERR), ('PATHITEM("",1,1)', ERR),
            ('PATHITEM(BLANK(),1,1)', BLANK), ('PATHITEM("1|2|3",4,1)', BLANK), ('PATHITEM(" 7 |8",1,1)', 7),
            ('PATHITEM("1,000|2",1,1)', 1000), ('PATHITEM("(5)|2",1,1)', -5), ('PATHITEM("5-|2",1,1)', -5),
            ('PATHITEM("$5|2",1,1)', 5), ('PATHITEM("1e2|4",1,1)', 100), ('PATHITEM("2.5|2",1,1)', 2),
            ('PATHITEM("-2.5|2",1,1)', -2), ('PATHITEM("1.5|2",1,1)', 2), ('PATHITEM(".5|2",1,1)', 0),
            ('PATHITEM("0x10|2",1,1)', ERR), ('PATHITEM("1e20|2",1,1)', ERR), ('PATHITEM("1 2|3",1,1)', ERR),
            ('PATHITEM("-9223372036854775808|1",1,1)', -9223372036854775808), ('PATHITEM("-9223372036854775809|1",1,1)', ERR),
            ('PATHITEM("1|2|3")', ERR), ('PATHITEM("1|2|3",1,2,3)', ERR),
            ('PATHITEMREVERSE("a|b|c",1)', "c"), ('PATHITEMREVERSE("a|b|c",3)', "a"), ('PATHITEMREVERSE("a|b|c",4)', BLANK),
            ('PATHITEMREVERSE("a|b|c",0)', BLANK), ('PATHITEMREVERSE("a|b|c",1.5)', "b"), ('PATHITEMREVERSE("1|2|",1)', ""),
            ('PATHITEMREVERSE("",1)', ""), ('PATHITEMREVERSE("",2)', BLANK), ("PATHITEMREVERSE(BLANK(),1)", BLANK),
            ('PATHITEMREVERSE("1|2|3",3,1)', 1), ('PATHITEMREVERSE("a|b",1,1)', ERR), ("PATHITEMREVERSE(123,1)", Text("123")),
            ('PATHCONTAINS("1|2|3",2)', True), ('PATHCONTAINS("1|2|3","2")', True), ('PATHCONTAINS("1|2|3",5)', False),
            ('PATHCONTAINS("1|2|3","")', False), ('PATHCONTAINS("1||3","")', True), ('PATHCONTAINS("","")', True),
            ('PATHCONTAINS("1|2|3",BLANK())', False), ('PATHCONTAINS(BLANK(),"")', False), ('PATHCONTAINS("1|2|3","1|2")', False),
            ('PATHCONTAINS("a|b|c","B")', True), ('PATHCONTAINS("1.0|2",2.0)', True), ('PATHCONTAINS("1.0|2","1")', False),
            ('PATHCONTAINS(" 1 | 2 ","2")', False), ('PATHCONTAINS("TRUE|b",TRUE())', True), ('PATHCONTAINS("true|b",TRUE())', True),
            ('PATHCONTAINS("straße|b","STRASSE")', True), ('PATHCONTAINS("É|b","é")', True), ('PATHCONTAINS("1|2|3",1.5)', False),
            ('PATHCONTAINS("1")', ERR), ('PATHCONTAINS("1","2","3")', ERR),
        ])

    def test_yearfrac(self) -> None:
        self.check([
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,12,31))", 1), ("YEARFRAC(DATE(2020,1,31),DATE(2020,3,31))", "0.166666666666667"),
            ("YEARFRAC(DATE(2020,1,30),DATE(2020,2,29))", "0.0805555555555556"),
            ("YEARFRAC(DATE(2020,2,28),DATE(2020,3,31))", "0.0916666666666667"),
            ("YEARFRAC(DATE(2020,3,31),DATE(2020,2,29))", "0.0861111111111111"),
            ("YEARFRAC(DATE(2021,2,28),DATE(2021,3,31))", "0.0861111111111111"),
            ("YEARFRAC(DATE(2020,2,29),DATE(2021,2,28))", 1), ("YEARFRAC(DATE(2021,3,1),DATE(2020,1,1))", "1.16666666666667"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,1,1))", 0), ("YEARFRAC(DATE(2000,1,1),DATE(2024,6,15))", "24.4555555555556"),
            ("YEARFRAC(DATE(2020,3,31),DATE(2020,3,29),0)", "0.00555555555555556"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,12,31),1)", "0.997267759562842"),
            ("YEARFRAC(DATE(2019,2,28),DATE(2020,2,29),1)", "1.00136798905609"),
            ("YEARFRAC(DATE(2019,3,1),DATE(2020,3,2),1)", "1.00410396716826"),
            ("YEARFRAC(DATE(2019,3,1),DATE(2020,2,27),1)", "0.994520547945206"),
            ("YEARFRAC(DATE(2020,3,1),DATE(2020,4,1),1)", "0.0846994535519126"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2120,1,1),1)", "99.9979398210897"),
            ("YEARFRAC(DATE(2012,2,29),DATE(2016,2,29),1)", "3.99835796387521"),
            ("YEARFRAC(DATE(2019,12,31),DATE(2021,1,1),1)", "1.00456204379562"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,12,31),2)", "1.01388888888889"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2021,1,1),3)", "1.0027397260274"),
            ("YEARFRAC(DATE(2021,2,28),DATE(2021,3,31),4)", "0.0888888888888889"),
            ("YEARFRAC(DATE(2020,2,29),DATE(2021,2,28),4)", "0.997222222222222"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),5)", ERR), ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),-1)", ERR),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),1.5)", "0.505555555555556"),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),0.5)", "0.497267759562842"), ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),4.5)", ERR),
            ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),-0.4)", "0.5"), ("YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),BLANK())", "0.5"),
            ('YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),"1")', "0.497267759562842"),
            ('YEARFRAC(DATE(2020,1,1),DATE(2020,7,1),"x")', ERR),
            ("YEARFRAC(BLANK(),DATE(2020,7,1))", "120.502777777778"), ("YEARFRAC(BLANK(),BLANK())", BLANK),
            ('YEARFRAC("2020-01-01","2020-07-01")', "0.5"), ('YEARFRAC("abc",DATE(2020,1,1))', ERR),
            ("YEARFRAC(43831,44000)", "0.463888888888889"), ("YEARFRAC(-1,5)", "0.0138888888888889"),
            ("YEARFRAC(1.9,2.1)", "0.00277777777777778"), ("YEARFRAC(TRUE(),FALSE())", 0), ("YEARFRAC(TRUE(),5)", "0.0111111111111111"),
            ("YEARFRAC(2958465,1)", 8100), ("YEARFRAC(2958466,1)", ERR), ("YEARFRAC(1E+20,5)", ERR),
            ("YEARFRAC(59,61,0)", "0.0111111111111111"), ("YEARFRAC(58,62,1)", "0.010958904109589"),
            ("YEARFRAC(-693593,0)", "1898.99722222222"), ("YEARFRAC(-1000000,0)", "2737.91111111111"),
            ("YEARFRAC(DATE(2020,1,1))", ERR), ("YEARFRAC(DATE(2020,1,1),DATE(2020,2,1),0,1)", ERR),
        ])

    def test_networkdays(self) -> None:
        self.check([
            ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31))", 23), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,7))", 5),
            ("NETWORKDAYS(DATE(2024,1,6),DATE(2024,1,7))", 0), ("NETWORKDAYS(DATE(2024,1,7),DATE(2024,1,6))", 0),
            ("NETWORKDAYS(DATE(2024,1,31),DATE(2024,1,1))", -23), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,1))", 1),
            ("NETWORKDAYS(DATE(2024,1,6),DATE(2024,1,6))", 0), ("NETWORKDAYS(DATE(2020,1,1),DATE(2024,12,31))", 1305),
            ("NETWORKDAYS(DATE(2024,1,5)+0.9,DATE(2024,1,1))", -5), ("NETWORKDAYS(DATE(2024,1,1)+0.5,DATE(2024,1,5)+0.9)", 5),
            ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31),7)", 23), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31),11)", 27),
            ("NETWORKDAYS(DATE(2024,1,6),DATE(2024,1,21),1)", 10), ("NETWORKDAYS(DATE(2024,1,6),DATE(2024,1,21),7)", 11),
            ("NETWORKDAYS(DATE(2024,1,6),DATE(2024,1,21),17)", 13), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),12)", 12),
            ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),0)", ERR), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),8)", ERR),
            ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),10)", ERR), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),18)", ERR),
            ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),BLANK())", ERR), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),1.5)", 10),
            ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),TRUE())", 10),
            ('NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),"0000011")', 12), ('NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),"0000012")', 12),
            ('NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),"1000001")', ERR), ('NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),"0000000")', ERR),
            ('NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,14),"abc")', ERR),
            ("NETWORKDAYS(BLANK(),DATE(2024,1,5))", 32355), ("NETWORKDAYS(DATE(2024,1,5),BLANK())", -32355),
            ("NETWORKDAYS(BLANK(),BLANK())", BLANK), ("NETWORKDAYS(0,6)", 5), ("NETWORKDAYS(-5,5)", 9),
            ("NETWORKDAYS(TRUE(),5)", 4), ('NETWORKDAYS("2024-01-01","2024-01-31")', 23), ('NETWORKDAYS("x",DATE(2024,1,5))', ERR),
            ("NETWORKDAYS(2958465,2958465)", 1), ("NETWORKDAYS(DATE(1900,1,1),DATE(9999,12,31))", 2113190),
            ("NETWORKDAYS(DATE(2024,1,1))", ERR), ("NETWORKDAYS(DATE(2024,1,1),DATE(2024,1,31),1,1,2)", ERR),
        ])

    def test_usercultures_and_type_tests(self) -> None:
        self.check([
            ("USERCULTURE()", "en-US"), ("USERCULTURE(1)", ERR), ("LEN(USERCULTURE())", 5), ("UPPER(USERCULTURE())", "EN-US"),
            ("ISBOOLEAN(TRUE())", True), ("ISBOOLEAN(FALSE())", True), ("ISBOOLEAN(1)", False), ('ISBOOLEAN("TRUE")', False),
            ("ISBOOLEAN(BLANK())", False), ("ISSTRING(\"abc\")", True), ('ISSTRING("")', True), ("ISSTRING(1)", False),
            ("ISSTRING(BLANK())", False), ("ISSTRING(TRUE())", False), ('ISSTRING(1&"a")', True),
            ("ISNUMERIC(1)", True), ("ISNUMERIC(1.5)", True), ("ISNUMERIC(1/0)", True), ("ISNUMERIC(0/0)", True),
            ("ISNUMERIC(CURRENCY(2.5))", True), ('ISNUMERIC("1")', False), ("ISNUMERIC(TRUE())", False), ("ISNUMERIC(BLANK())", False),
            ("ISNUMERIC(DATE(2020,1,1))", False), ("ISNUMERIC(NOW())", False), ("ISNUMERIC(YEAR(NOW()))", True),
            ("ISDATETIME(DATE(2020,1,1))", True), ("ISDATETIME(NOW())", True), ("ISDATETIME(TIME(1,2,3))", True),
            ("ISDATETIME(DATE(2020,1,1)+1)", True), ("ISDATETIME(DATE(2020,1,1)-DATE(2019,1,1))", True),
            ("ISDATETIME(1)", False), ('ISDATETIME("2020-01-01")', False), ("ISDATETIME(BLANK())", False),
            ("ISBOOLEAN()", ERR), ("ISNUMERIC(1,2)", ERR),
        ])


if __name__ == "__main__":
    unittest.main()
