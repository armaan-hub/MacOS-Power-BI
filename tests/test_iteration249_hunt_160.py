"""Task 160 (dax-hunt-160): CONTAINSROW and v IN table compare each value with its column.

A value of a type class that differs from its column (text, True/False, or numeric where Integer, Number, Currency and Date
compare with each other) is a query-level error in Power BI: IFERROR does not catch it and an untaken IF branch still fails.
BLANK() and a variant value compare with everything. Values copied from the measured Power BI answers.
"""

import unittest

from tools.dax_oracle_diff import local


class TestIteration249Hunt160(unittest.TestCase):
    def test_text_value_against_a_number_column_is_a_query_error(self):
        self.assertTrue(local('CONTAINSROW(VALUES(Facts[Sales]),"East")').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IFERROR(CONTAINSROW(VALUES(Facts[Sales]),"East"),"E")').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Sales]),"East"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,"East" IN VALUES(Facts[Sales]))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",SUM(Facts[Sales])),"East"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",SUM(Facts[Sales])),FORMAT(1,"0")))').startswith("LOCAL-REJECT"))

    def test_number_value_against_a_text_column_is_a_query_error(self):
        self.assertTrue(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),1))").startswith("LOCAL-REJECT"))
        self.assertTrue(local("IF(TRUE(),1,1 IN VALUES(Facts[Region]))").startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SELECTCOLUMNS(Facts,"r",Facts[Region]),1))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),CURRENCY(1)))').startswith("LOCAL-REJECT"))

    def test_true_false_against_text_or_number_is_a_query_error(self):
        self.assertTrue(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),TRUE()))").startswith("LOCAL-REJECT"))
        self.assertTrue(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Sales]),TRUE()))").startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),"East",TRUE()))').startswith("LOCAL-REJECT"))

    def test_date_against_text_is_a_query_error(self):
        self.assertTrue(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),DATE(2020,1,1)))").startswith("LOCAL-REJECT"))

    def test_second_column_mismatch_is_a_query_error(self):
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),1,"x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(ADDCOLUMNS(VALUES(Facts[Region]),"n",1),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t","a"),1))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",1),"a"))').startswith("LOCAL-REJECT"))

    def test_table_constructor_column_type_is_checked(self):
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW({1,2},"a"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW({"a","b"},1))').startswith("LOCAL-REJECT"))

    def test_multi_column_table_constructor_in_an_equality_is_a_query_error(self):
        self.assertTrue(local('IF(TRUE(),1,{("East",1)} = {("East",1)})').startswith("LOCAL-REJECT"))

    def test_compatible_types_compute(self):
        self.assertEqual(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Sales]),1))"), "1")
        self.assertEqual(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Sales]),DATE(2020,1,1)))"), "1")
        self.assertEqual(local("IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),BLANK()))"), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",SUM(Facts[Sales])),VALUE("1")))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),"East"&""))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),1&""))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",SUM(Facts[Sales])),1.5))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",COUNTROWS(Facts)),1.5))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",IF(1=1,1,"a")),"a"))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),"East",1.5))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),"East",1))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW({1,2},1))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW({"a","b"},"a"))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(ADDCOLUMNS(VALUES(Facts[Region]),"x",1),"East",1))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(ADDCOLUMNS(VALUES(Facts[Region]),"x",1,"y",2),"East",1,2))'), "1")
        self.assertEqual(local('IFERROR(CONTAINSROW(ADDCOLUMNS(VALUES(Facts[Region]),"x",1),"East",1),"E")'), "True")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",IF(1=1,1,"a")),"a"))'), "1")

    def test_unknown_or_variant_values_are_left_alone(self):
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,"t",IF(1=1,1,"a")),"a"))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),BLANK()))'), "1")


    def test_measured_2026_11_15_all_columns_and_added_column(self):
        # live Power BI, 2026-11-15: both are errors, also inside IFERROR; the third computes False
        self.assertTrue(local('CONTAINSROW(ADDCOLUMNS(Facts,"a",1),1,2,3,4,5)').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IFERROR(CONTAINSROW(ADDCOLUMNS(Facts,"a",1),1,2,3,4,5),-1)').startswith("LOCAL-REJECT"))
        self.assertTrue(local('CONTAINSROW(ALL(Facts[Region],Facts[Sales]),"East","x")').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IFERROR(CONTAINSROW(ALL(Facts[Region],Facts[Sales]),"East","x"),-1)').startswith("LOCAL-REJECT"))
        self.assertTrue(local('CONTAINSROW(ALLNOBLANKROW(Facts[Region],Facts[Sales]),"East","x")').startswith("LOCAL-REJECT"))
        self.assertEqual(local('CONTAINSROW(ALL(Facts[Region],Facts[Sales]),"East",100)'), "False")


if __name__ == "__main__":
    unittest.main()
