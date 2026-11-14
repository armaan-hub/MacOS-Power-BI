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

    def test_review_summarizecolumns_duplicates_are_static_query_errors(self):
        """Power BI (measured): the untaken IF branch still fails, so these are query-level errors."""
        for expression in (
            'IF(FALSE(),COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],Facts[Region])),1)',
            'IF(FALSE(),COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],Facts[region],"t",1)),1)',
            'IF(FALSE(),COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],"Region",1)),1)',
            'IF(FALSE(),COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],"t",1,"T",2)),1)',
            'IF(FALSE(),COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],Facts[Quantity],"Quantity",1)),1)',
            'IF(FALSE(),COUNTROWS(SUMMARIZECOLUMNS(ROLLUPADDISSUBTOTAL(Facts[Region],"Region"),"t",1)),1)',
            'COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],ROLLUPADDISSUBTOTAL(Facts[Quantity],"x",Facts[Note],"X"),"t",1))',
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT"), expression)
        self.assertEqual(local('COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],"Quantity",1))'), "3")
        self.assertEqual(local('COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],FILTER(Facts,Facts[Sales]>0),"t",1))'), "2")

    def test_review_groupby_duplicate_new_names_are_static_query_errors(self):
        self.assertTrue(local('IF(FALSE(),COUNTROWS(GROUPBY(Facts,Facts[Region],"n",SUMX(CURRENTGROUP(),1),"N",SUMX(CURRENTGROUP(),2))),1)').startswith("LOCAL-REJECT"))
        self.assertEqual(local('COUNTROWS(GROUPBY(Facts,Facts[Region],"Quantity",SUMX(CURRENTGROUP(),Facts[Sales])))'), "3")
        self.assertEqual(local('SUMX(GROUPBY(Facts,Facts[Region],"Quantity",SUMX(CURRENTGROUP(),Facts[Sales])),[Quantity])'), "31.5")

    def test_review_new_name_written_like_a_column_reference_clashes_with_that_column(self):
        """Power BI (measured): the name "Facts[Region]" clashes with the column Facts[Region]; "Facts[Quantity]" does not clash with a group column Region."""
        for expression in (
            'COUNTROWS(SUMMARIZE(Facts,Facts[Region],"Facts[Region]",1))',
            'COUNTROWS(SUMMARIZE(Facts,Facts[Region],"\'Facts\'[Region]",1))',
            'COUNTROWS(ADDCOLUMNS(Facts,"Facts[Region]",1))',
            'COUNTROWS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region]),"Facts[Region]",1))',
            'COUNTROWS(ADDCOLUMNS(VALUES(Facts[Region]),"Facts[Region]",1))',
            'COUNTROWS(SUMMARIZECOLUMNS(Facts[Region],"Facts[Region]",1))',
            'COUNTROWS(SELECTCOLUMNS(Facts,Facts[Region],"facts[region]",1))',
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT"), expression)
        self.assertEqual(local('COUNTROWS(SUMMARIZE(Facts,Facts[Region],"Facts[Quantity]",1))'), "3")
        self.assertEqual(local('COUNTROWS(SUMMARIZE(Facts,Facts[Region],"[Region]",1))'), "3")
        self.assertEqual(local('COUNTROWS(ADDCOLUMNS(SUMMARIZE(Facts,Facts[Region]),"Facts[Quantity]",1))'), "3")
        self.assertEqual(local('COUNTROWS(SELECTCOLUMNS(Facts,Facts[Region],"Facts[Sales]",1))'), "6")

    def test_review_select_columns_after_a_plain_column_still_checks_names(self):
        self.assertTrue(local('COUNTROWS(SELECTCOLUMNS(Facts,Facts[Region],"a",1,"A",2))').startswith("LOCAL-REJECT"))
        self.assertEqual(local('COUNTROWS(SELECTCOLUMNS(Facts,Facts[Region],"Region",1))'), "6")


if __name__ == "__main__":
    unittest.main()
