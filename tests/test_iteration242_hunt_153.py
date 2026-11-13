"""Task 153 (dax-hunt-153): fresh Power BI hunt, batch 11. Exact assertions copied from the measured Power BI answers (spec group fm).
Family A: MOD of an Int64, Double or date dividend with a Double divisor is the IEEE fmod with the sign fix (no snapping to zero);
MOD of two Int64s, and CURRENCY MOD, stay as they were.
Family B: a DATEDIFF date outside 01/01/0100..12/31/9999 fails the whole query, so IFERROR cannot catch it (a hard error); the other
date functions keep their catchable errors, and an in-range DATEDIFF is unchanged.
"""
import unittest

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


class TestIteration242Hunt153(unittest.TestCase):
    def test_hunt_153_measured_answers(self):
        self.assertTrue(_same_15('MOD(1,1E-5)', '9.9999999999182E-06'), 'MOD(1,1E-5)')
        self.assertTrue(_same_15('MOD(-1,0.1)', '5.55111512312578E-17'), 'MOD(-1,0.1)')
        self.assertTrue(_same_15('MOD(1,0.1)', '0.1'), 'MOD(1,0.1)')
        self.assertTrue(_same_15('MOD(-1,0.3)', '0.2'), 'MOD(-1,0.3)')
        self.assertTrue(_same_15('MOD(-2,0.2)', '1.11022302462516E-16'), 'MOD(-2,0.2)')
        self.assertTrue(_same_15('MOD(-1,0.01)', '2.08166817117217E-17'), 'MOD(-1,0.01)')
        self.assertTrue(_same_15('MOD(-7,0.7)', '0.7'), 'MOD(-7,0.7)')
        self.assertTrue(_same_15('MOD(-1,3)', '2'), 'MOD(-1,3)')
        self.assertTrue(_same_15('MOD(-1,1E-3)', '2.08166817117217E-17'), 'MOD(-1,1E-3)')
        self.assertTrue(_same_15('MOD(-0.5,1E-5)', '4.09015269570157E-17'), 'MOD(-0.5,1E-5)')
        self.assertTrue(_same_15('MOD(-1,-1E-5)', '-9.9999999999182E-06'), 'MOD(-1,-1E-5)')
        self.assertTrue(_same_15('MOD(1,-1E-5)', '-8.18030539140313E-17'), 'MOD(1,-1E-5)')
        self.assertTrue(_same_15('MOD(-3,1E-4)', '1.43765208071578E-16'), 'MOD(-3,1E-4)')
        self.assertTrue(_same_15('MOD(-1,7E-6)', '5.999999999985E-06'), 'MOD(-1,7E-6)')
        self.assertTrue(_same_15('MOD(-100,1E-5)', '8.18030539140313E-15'), 'MOD(-100,1E-5)')
        self.assertTrue(_same_15('MOD(5,1E-5)', '9.99999999959099E-06'), 'MOD(5,1E-5)')
        self.assertTrue(_same_15('MOD(-1,0.05)', '5.55111512312578E-17'), 'MOD(-1,0.05)')
        self.assertTrue(_same_15('MOD(-1.5,0.5)', '0'), 'MOD(-1.5,0.5)')
        self.assertTrue(_same_15('MOD(-1,1E-10)', '3.64321973154977E-17'), 'MOD(-1,1E-10)')
        self.assertEqual(local('MOD(-1,1E-5)&"z"'), '8.18030539140313E-17z', 'MOD(-1,1E-5)&"z"')
        self.assertEqual(local('MOD(-1,1E-5)=0'), 'False', 'MOD(-1,1E-5)=0')
        self.assertTrue(_same_15('MOD(-1,CURRENCY(0.1))', '0'), 'MOD(-1,CURRENCY(0.1))')
        self.assertTrue(_same_15('MOD(-1,1E-5)*1E10', '8.18030539140313E-07'), 'MOD(-1,1E-5)*1E10')
        self.assertTrue(_same_15('MOD(DATE(2020,1,1),1E-5)', '9.99999641449034E-06'), 'MOD(DATE(2020,1,1),1E-5)')
        self.assertTrue(_same_15('MOD(-1,DIVIDE(1,100000))', '8.18030539140313E-17'), 'MOD(-1,DIVIDE(1,100000))')
        self.assertTrue(local('IFERROR(DATEDIFF(DATE(9999,12,31)+1,DATE(9999,12,31),DAY),"E")').startswith("LOCAL-REJECT"), 'IFERROR(DATEDIFF(DATE(9999,12,31)+1,DATE(9999,12,31),DAY),"E")')
        self.assertTrue(local('DATEDIFF(DATE(9999,12,31),DATE(9999,12,31)+3,DAY)').startswith("LOCAL-REJECT"), 'DATEDIFF(DATE(9999,12,31),DATE(9999,12,31)+3,DAY)')
        self.assertTrue(local('IFERROR(DATEDIFF(DATE(9999,12,31),DATE(9999,12,31)+3,DAY),"E")').startswith("LOCAL-REJECT"), 'IFERROR(DATEDIFF(DATE(9999,12,31),DATE(9999,12,31)+3,DAY),"E")')
        self.assertEqual(local('IFERROR(YEAR(DATE(9999,12,31)+3),"E")'), 'E', 'IFERROR(YEAR(DATE(9999,12,31)+3),"E")')
        self.assertTrue(local('IFERROR(DATEDIFF(DATE(100,1,1)-3,DATE(100,1,1),DAY),"E")').startswith("LOCAL-REJECT"), 'IFERROR(DATEDIFF(DATE(100,1,1)-3,DATE(100,1,1),DAY),"E")')
        self.assertTrue(local('IFERROR(DATEDIFF(DATE(2020,1,1)-1E8,DATE(2020,1,1),DAY),"E")').startswith("LOCAL-REJECT"), 'IFERROR(DATEDIFF(DATE(2020,1,1)-1E8,DATE(2020,1,1),DAY),"E")')
        self.assertTrue(local('IFERROR(DATEDIFF(DATE(9999,12,31)+3,DATE(9999,12,31),MONTH),"E")').startswith("LOCAL-REJECT"), 'IFERROR(DATEDIFF(DATE(9999,12,31)+3,DATE(9999,12,31),MONTH),"E")')
        self.assertTrue(_same_15('IFERROR(DATEDIFF(DATE(9999,12,31)+0.5,DATE(9999,12,31),HOUR),"E")', '-12'), 'IFERROR(DATEDIFF(DATE(9999,12,31)+0.5,DATE(9999,12,31),HOUR),"E")')
        self.assertEqual(local('IFERROR(EDATE(DATE(9999,12,31)+3,1),"E")'), 'E', 'IFERROR(EDATE(DATE(9999,12,31)+3,1),"E")')
        self.assertEqual(local('IFERROR(EOMONTH(DATE(9999,12,31)+3,0),"E")'), 'E', 'IFERROR(EOMONTH(DATE(9999,12,31)+3,0),"E")')
        self.assertEqual(local('IFERROR(WEEKDAY(DATE(9999,12,31)+3),"E")'), 'E', 'IFERROR(WEEKDAY(DATE(9999,12,31)+3),"E")')
        self.assertEqual(local('IFERROR(FORMAT(DATE(9999,12,31)+3,"yyyy"),"E")'), 'E', 'IFERROR(FORMAT(DATE(9999,12,31)+3,"yyyy"),"E")')



if __name__ == "__main__":
    unittest.main()
