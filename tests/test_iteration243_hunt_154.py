"""Task 154 (dax-hunt-154): fresh Power BI hunt, batch 12. Exact assertions copied from the measured Power BI answers (spec rows with PERCENTILEX).
Family A: PERCENTILEX.EXC / PERCENTILEX.INC check k against the rows iterated before the all-BLANK result: an out-of-range k is an
error even when every value is BLANK; only a valid k gives BLANK. An empty table stays BLANK with no range check.
"""
import unittest

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


class TestIteration243Hunt154(unittest.TestCase):
    def test_hunt_154_measured_answers(self):
        self.assertTrue(_same_15('PERCENTILEX.INC(ALL(Facts),RANKX(ALL(Facts[Region]),SUM(Facts[Sales])),0.5)', '1'), 'PERCENTILEX.INC(ALL(Facts),RANKX(ALL(Facts[Region]),SUM(Facts[Sales])),0.5)')
        self.assertTrue(local('PERCENTILEX.EXC(Facts,DIVIDE(Facts[Sales],Facts[Quantity]),0.1)').startswith('LOCAL-REJECT'), 'PERCENTILEX.EXC(Facts,DIVIDE(Facts[Sales],Facts[Quantity]),0.1)')
        self.assertTrue(local('PERCENTILEX.EXC(ADDCOLUMNS(Facts,"k",2.5),BLANK(),0.05)').startswith('LOCAL-REJECT'), 'PERCENTILEX.EXC(ADDCOLUMNS(Facts,"k",2.5),BLANK(),0.05)')
        self.assertTrue(local('PERCENTILEX.EXC(ALL(Facts),IF(Facts[Sales]>0,Facts[Sales],0),0)').startswith('LOCAL-REJECT'), 'PERCENTILEX.EXC(ALL(Facts),IF(Facts[Sales]>0,Facts[Sales],0),0)')
        self.assertTrue(_same_15('PERCENTILEX.INC(Facts,COUNTROWS(Facts),0.25)', '6'), 'PERCENTILEX.INC(Facts,COUNTROWS(Facts),0.25)')
        self.assertTrue(_same_15('PERCENTILEX.EXC(Facts,IF(Facts[Sales]>0,Facts[Sales],0),0.25)', '0'), 'PERCENTILEX.EXC(Facts,IF(Facts[Sales]>0,Facts[Sales],0),0.25)')
        self.assertEqual(local('PERCENTILEX.EXC(ADDCOLUMNS(Facts,"k",2.5),BLANK(),0.5)'), 'BLANK', 'PERCENTILEX.EXC(ADDCOLUMNS(Facts,"k",2.5),BLANK(),0.5)')
        self.assertEqual(local('PERCENTILEX.EXC(Facts,BLANK(),0.5)'), 'BLANK', 'PERCENTILEX.EXC(Facts,BLANK(),0.5)')
        self.assertEqual(local('PERCENTILEX.INC(Facts,BLANK(),0.5)'), 'BLANK', 'PERCENTILEX.INC(Facts,BLANK(),0.5)')
        self.assertEqual(local('PERCENTILEX.INC(Facts,BLANK(),0)'), 'BLANK', 'PERCENTILEX.INC(Facts,BLANK(),0)')
        self.assertEqual(local('PERCENTILEX.INC(Facts,BLANK(),1)'), 'BLANK', 'PERCENTILEX.INC(Facts,BLANK(),1)')
        self.assertTrue(local('PERCENTILEX.INC(Facts,BLANK(),1.5)').startswith('LOCAL-REJECT'), 'PERCENTILEX.INC(Facts,BLANK(),1.5)')
        self.assertEqual(local('PERCENTILEX.EXC(FILTER(Facts,FALSE()),Facts[Sales],0.5)'), 'BLANK', 'PERCENTILEX.EXC(FILTER(Facts,FALSE()),Facts[Sales],0.5)')
        self.assertEqual(local('PERCENTILEX.INC(FILTER(Facts,FALSE()),Facts[Sales],0.5)'), 'BLANK', 'PERCENTILEX.INC(FILTER(Facts,FALSE()),Facts[Sales],0.5)')
        self.assertEqual(local('PERCENTILEX.EXC(FILTER(Facts,FALSE()),Facts[Sales],0)'), 'BLANK', 'PERCENTILEX.EXC(FILTER(Facts,FALSE()),Facts[Sales],0)')
        self.assertTrue(_same_15('PERCENTILEX.EXC({1},[Value],0.5)', '1'), 'PERCENTILEX.EXC({1},[Value],0.5)')
        self.assertTrue(local('PERCENTILEX.EXC({1},[Value],0.4)').startswith('LOCAL-REJECT'), 'PERCENTILEX.EXC({1},[Value],0.4)')
        self.assertTrue(local('PERCENTILEX.EXC({1,2},[Value],0.3)').startswith('LOCAL-REJECT'), 'PERCENTILEX.EXC({1,2},[Value],0.3)')
        self.assertTrue(_same_15('PERCENTILEX.EXC({1,2},[Value],0.34)', '1.02'), 'PERCENTILEX.EXC({1,2},[Value],0.34)')
        self.assertEqual(local('PERCENTILEX.EXC({1,2},BLANK(),0.5)'), 'BLANK', 'PERCENTILEX.EXC({1,2},BLANK(),0.5)')
        self.assertTrue(_same_15('PERCENTILEX.EXC({BLANK(),1},[Value],0.5)', '0.5'), 'PERCENTILEX.EXC({BLANK(),1},[Value],0.5)')
        self.assertEqual(local('PERCENTILEX.EXC({BLANK(),BLANK()},[Value],0.5)'), 'BLANK', 'PERCENTILEX.EXC({BLANK(),BLANK()},[Value],0.5)')
        self.assertEqual(local('PERCENTILEX.INC({BLANK(),BLANK()},[Value],0.5)'), 'BLANK', 'PERCENTILEX.INC({BLANK(),BLANK()},[Value],0.5)')
        self.assertTrue(_same_15('PERCENTILEX.EXC({1,2,3},IF([Value]=2,BLANK(),[Value]),0.5)', '1'), 'PERCENTILEX.EXC({1,2,3},IF([Value]=2,BLANK(),[Value]),0.5)')
        self.assertEqual(local('IFERROR(PERCENTILEX.EXC(Facts,BLANK(),0.5),"E")'), 'BLANK', 'IFERROR(PERCENTILEX.EXC(Facts,BLANK(),0.5),"E")')
        self.assertTrue(local('PERCENTILEX.EXC({"a"},[Value],0.5)').startswith('LOCAL-REJECT'), 'PERCENTILEX.EXC({"a"},[Value],0.5)')


if __name__ == '__main__':
    unittest.main()
