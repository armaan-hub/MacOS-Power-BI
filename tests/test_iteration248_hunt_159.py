"""Task 159 (dax-hunt-159): duplicate column names in SUMMARIZE / SUMMARIZECOLUMNS / GROUPBY / ADDCOLUMNS / SELECTCOLUMNS.

Power BI rejects the whole query before it evaluates, so IFERROR does not catch these and an untaken IF branch still fails.
The local engine raises them statically (LOCAL-REJECT). Values copied from the measured Power BI answers.
"""

import unittest

from tools.dax_oracle_diff import local


class TestIteration248Hunt159(unittest.TestCase):
    def test_group_column_given_twice_is_a_query_error(self):
        self.assertTrue(local("COUNTROWS(SUMMARIZE(Facts,Facts[Region],Facts[Region]))").startswith("LOCAL-REJECT"))
        self.assertTrue(local("IF(FALSE(),COUNTROWS(SUMMARIZE(Facts,Facts[Region],Facts[Region])),1)").startswith("LOCAL-REJECT"))
        self.assertTrue(local("IFERROR(COUNTROWS(SUMMARIZE(Facts,Facts[Region],Facts[Region])),-1)").startswith("LOCAL-REJECT"))
        self.assertTrue(local("IFERROR(SUMX(SUMMARIZE(Facts,Facts[Region],Facts[Region]),1),-1)").startswith("LOCAL-REJECT"))
        self.assertTrue(local('IFERROR(COUNTROWS(SUMMARIZE(FILTER(Facts,Facts[Sales]>0),Facts[Region],Facts[Region])),-1)').startswith("LOCAL-REJECT"))
        self.assertTrue(local("IFERROR(COUNTROWS(SUMMARIZE(Facts,Facts[Region],Facts[Quantity],Facts[region])),-1)").startswith("LOCAL-REJECT"))

    def test_group_column_inside_rollup_counts_as_given(self):
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,ROLLUP(Facts[Region],Facts[Region])),"East"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],Facts[region]),"East"))').startswith("LOCAL-REJECT"))

    def test_new_column_named_like_a_group_column_is_a_query_error(self):
        self.assertTrue(local('IF(FALSE(),COUNTROWS(SUMMARIZE(Facts,Facts[Region],"Region",1)),1)').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"Region",SUM(Facts[Sales])),"East"))').startswith("LOCAL-REJECT"))

    def test_two_new_columns_with_the_same_name_are_a_query_error(self):
        self.assertTrue(local('IF(FALSE(),COUNTROWS(SUMMARIZE(Facts,Facts[Region],"t",1,"t",2)),1)').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(FALSE(),COUNTROWS(SUMMARIZE(Facts,"t",1,"T",2)),1)').startswith("LOCAL-REJECT"))
        self.assertTrue(local('COUNTROWS(ADDCOLUMNS(Facts,"a",1,"A",2))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('COUNTROWS(SELECTCOLUMNS(Facts,"a",Facts[Sales],"A",2))').startswith("LOCAL-REJECT"))

    def test_empty_new_column_name_is_a_query_error(self):
        self.assertTrue(local('IFERROR(COUNTROWS(SUMMARIZE(Facts,Facts[Region],"",1)),-1)').startswith("LOCAL-REJECT"))

    def test_summarizecolumns_and_groupby_duplicates_are_query_errors(self):
        self.assertTrue(local("COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],Facts[Region]))").startswith("LOCAL-REJECT"))
        self.assertTrue(local("COUNTROWS(GROUPBY(Facts,Facts[Region],Facts[Region]))").startswith("LOCAL-REJECT"))

    def test_keep_cases_stay_exact(self):
        self.assertEqual(local('COUNTROWS(SUMMARIZE(Facts,"t",1))'), "1")
        self.assertEqual(local('COUNTROWS(SUMMARIZE(Facts,"a",1,"b",2))'), "1")
        self.assertEqual(local('COUNTROWS(SUMMARIZE(Facts,Facts[Region],"Quantity",1))'), "3")
        self.assertEqual(local('COUNTROWS(SUMMARIZE(Facts,Facts[Region],"Sales",SUM(Facts[Sales])))'), "3")
        self.assertEqual(local('COUNTROWS(ALL(Facts[Region],Facts[Region]))'), "3")


if __name__ == "__main__":
    unittest.main()
