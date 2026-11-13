"""Task 155 (dax-hunt-155): fresh Power BI hunt, batch 13. Exact assertions copied from the measured Power BI answers (spec rows with CONVERT(..., INTEGER)).
Family A: CONVERT of a text to INTEGER parses the text as a decimal and rounds half to even (CONVERT("0.5",INTEGER) is 0, CONVERT("2.5",INTEGER) is 2).
A number argument keeps rounding half away from zero (CONVERT(2.5,INTEGER) is 3). Error rows are checked as LOCAL-REJECT (an error).
"""
import unittest

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


class TestIteration244Hunt155(unittest.TestCase):
    def test_hunt_155_measured_answers(self):
        self.assertTrue(_same_15('CONVERT(0=1,INTEGER)', '0'), 'CONVERT(0=1,INTEGER)')
        self.assertEqual(local('CONVERT(BLANK(),INTEGER)'), 'BLANK', 'CONVERT(BLANK(),INTEGER)')
        self.assertTrue(local('CURRENCY(CONVERT(MAX(Facts[Region]),INTEGER))').startswith('LOCAL-REJECT'), 'CURRENCY(CONVERT(MAX(Facts[Region]),INTEGER))')
        self.assertTrue(_same_15('CONVERT(0,INTEGER)', '0'), 'CONVERT(0,INTEGER)')
        self.assertTrue(_same_15('IFERROR(CONVERT("12",INTEGER),"E")', '12'), 'IFERROR(CONVERT("12",INTEGER),"E")')
        self.assertTrue(_same_15('CONVERT(ISINTEGER(CONVERT("abc",DOUBLE)),INTEGER)', '0'), 'CONVERT(ISINTEGER(CONVERT("abc",DOUBLE)),INTEGER)')
        self.assertTrue(_same_15('FIXED(CONVERT(TIME(13,5,0),INTEGER),5,TRUE())', '1.00000'), 'FIXED(CONVERT(TIME(13,5,0),INTEGER),5,TRUE())')
        self.assertTrue(_same_15('VALUE(CONVERT(CONVERT(-1,CURRENCY),INTEGER))', '-1'), 'VALUE(CONVERT(CONVERT(-1,CURRENCY),INTEGER))')
        self.assertTrue(local('CONVERT(CONVERT("East",DOUBLE),INTEGER)').startswith('LOCAL-REJECT'), 'CONVERT(CONVERT("East",DOUBLE),INTEGER)')
        self.assertTrue(local('CONVERT("2020-02-29",INTEGER)').startswith('LOCAL-REJECT'), 'CONVERT("2020-02-29",INTEGER)')
        self.assertTrue(_same_15('IFERROR(CONVERT("x"="x",INTEGER),"E")', '1'), 'IFERROR(CONVERT("x"="x",INTEGER),"E")')
        self.assertTrue(_same_15('CONVERT(CONVERT(FIXED(TIME(13,5,0),0.5,TRUE()),INTEGER),STRING)', '0'), 'CONVERT(CONVERT(FIXED(TIME(13,5,0),0.5,TRUE()),INTEGER),STRING)')
        self.assertEqual(local('CONVERT(CONVERT(INT(ROUND(CONVERT(SUM(Facts[Sales]),DOUBLE),3)),INTEGER),DATETIME)'), '01/30/1900 00:00:00', 'CONVERT(CONVERT(INT(ROUND(CONVERT(SUM(Facts[Sales]),DOUBLE),3)),INTEGER),DATETIME)')
        self.assertTrue(_same_15('CONVERT("0.545",INTEGER)', '1'), 'CONVERT("0.545",INTEGER)')
        self.assertTrue(_same_15('CONVERT("0.5",INTEGER)', '0'), 'CONVERT("0.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("1.5",INTEGER)', '2'), 'CONVERT("1.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("2.5",INTEGER)', '2'), 'CONVERT("2.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("-0.5",INTEGER)', '0'), 'CONVERT("-0.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("0.6",INTEGER)', '1'), 'CONVERT("0.6",INTEGER)')
        self.assertTrue(_same_15('CONVERT("1",INTEGER)', '1'), 'CONVERT("1",INTEGER)')
        self.assertTrue(_same_15('CONVERT(0.545,INTEGER)', '1'), 'CONVERT(0.545,INTEGER)')
        self.assertTrue(_same_15('CONVERT(0.5,INTEGER)', '1'), 'CONVERT(0.5,INTEGER)')
        self.assertTrue(_same_15('CONVERT(1.5,INTEGER)', '2'), 'CONVERT(1.5,INTEGER)')
        self.assertTrue(_same_15('CONVERT(2.5,INTEGER)', '3'), 'CONVERT(2.5,INTEGER)')
        self.assertTrue(_same_15('CONVERT(FIXED(0.545,0.5),INTEGER)', '0'), 'CONVERT(FIXED(0.545,0.5),INTEGER)')
        self.assertTrue(_same_15('CONVERT(FIXED(0.545,2),INTEGER)', '1'), 'CONVERT(FIXED(0.545,2),INTEGER)')
        self.assertTrue(_same_15('CONVERT("0.55",INTEGER)', '1'), 'CONVERT("0.55",INTEGER)')
        self.assertTrue(_same_15('CONVERT("1.55",INTEGER)', '2'), 'CONVERT("1.55",INTEGER)')
        self.assertTrue(_same_15('CONVERT("1,234.5",INTEGER)', '1234'), 'CONVERT("1,234.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("3.5",INTEGER)', '4'), 'CONVERT("3.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("-1.5",INTEGER)', '-2'), 'CONVERT("-1.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("-2.5",INTEGER)', '-2'), 'CONVERT("-2.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("0.5000001",INTEGER)', '1'), 'CONVERT("0.5000001",INTEGER)')
        self.assertTrue(_same_15('CONVERT("4.5",INTEGER)', '4'), 'CONVERT("4.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("1E1",INTEGER)', '10'), 'CONVERT("1E1",INTEGER)')
        self.assertTrue(_same_15('CONVERT("2.50",INTEGER)', '2'), 'CONVERT("2.50",INTEGER)')
        self.assertTrue(_same_15('CONVERT(" 2.5 ",INTEGER)', '2'), 'CONVERT(" 2.5 ",INTEGER)')
        self.assertTrue(_same_15('CONVERT("$2.5",INTEGER)', '2'), 'CONVERT("$2.5",INTEGER)')
        self.assertTrue(local('CONVERT("2.5%",INTEGER)').startswith('LOCAL-REJECT'), 'CONVERT("2.5%",INTEGER)')
        self.assertTrue(_same_15('CONVERT("9007199254740993.5",INTEGER)', '9007199254740994'), 'CONVERT("9007199254740993.5",INTEGER)')
        self.assertTrue(_same_15('CONVERT("2.5",INTEGER)&""', '2'), 'CONVERT("2.5",INTEGER)&""')
        self.assertTrue(_same_15('CONVERT("2.5",INTEGER)*1', '2'), 'CONVERT("2.5",INTEGER)*1')
        self.assertTrue(_same_15('INT(CONVERT("2.5",INTEGER))', '2'), 'INT(CONVERT("2.5",INTEGER))')
        self.assertTrue(_same_15('CONVERT(TRUE(),INTEGER)', '1'), 'CONVERT(TRUE(),INTEGER)')
        self.assertTrue(local('CONVERT("TRUE",INTEGER)').startswith('LOCAL-REJECT'), 'CONVERT("TRUE",INTEGER)')
        self.assertTrue(_same_15('VAR t="2.5" RETURN CONVERT(t,INTEGER)', '2'), 'VAR t="2.5" RETURN CONVERT(t,INTEGER)')
        self.assertTrue(_same_15('CONVERT("2"&".5",INTEGER)', '2'), 'CONVERT("2"&".5",INTEGER)')
        self.assertTrue(_same_15('CONVERT(FORMAT(2.5,"0.0"),INTEGER)', '2'), 'CONVERT(FORMAT(2.5,"0.0"),INTEGER)')
        self.assertTrue(_same_15('SUMX({"0.5","2.5"},CONVERT([Value],INTEGER))', '2'), 'SUMX({"0.5","2.5"},CONVERT([Value],INTEGER))')

if __name__ == '__main__':
    unittest.main()
