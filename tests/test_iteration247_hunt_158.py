"""Task 158 (dax-hunt-158): fresh Power BI hunt, batch 12. Exact assertions, values copied from the measured Power BI answers.

Family C: a repeated group column of SUMMARIZE counts once; CONTAINSROW with two values over that width is a query-level error.

Families A (SIN, COS, TAN beyond 2*pi refused) and B (EXP of a negative argument in double) were reverted: the parity replay
showed saved, locked Power BI answers that match today (SIN(DATE(2020,1,1)), ISERROR(SIN(1E8+3.4E7)) is FALSE, EXP(-0.7)&"z").
"""

import unittest

from tools.dax_oracle_diff import local


class TestIteration247Hunt158(unittest.TestCase):
    # Family C: a repeated SUMMARIZE group column counts once
    def test_family_c_repeated_group_column_is_one_column(self):
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],Facts[Region]),"East",1))').startswith("LOCAL-REJECT"))

    def test_family_c_single_group_column_kept(self):
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region]),"East"))'), "1")


if __name__ == "__main__":
    unittest.main()
