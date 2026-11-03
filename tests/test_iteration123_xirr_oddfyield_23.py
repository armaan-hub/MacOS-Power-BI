"""Iteration 123: tests for Task 33 xirr-oddfyield-23 (XIRR, ODDFYIELD, PATHITEM with type argument)."""

import unittest
from tools import dax_oracle_diff as dax
from tools.dax_oracle_diff import same


class TestIteration123XirrOddfyield23(unittest.TestCase):
    def test_part_b_oddfyield(self) -> None:
        # Live Power BI measured example from plan
        res = dax.local("ODDFYIELD(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),0.0575,84.5,100,2,0)")
        self.assertTrue(same("0.0772455415972989", res))

        # Part B error cases (frequency 3, negative rate, basis 5, etc.)
        self.assertTrue(dax.local("ODDFYIELD(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),0.0575,84.5,100,3,0)").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("ODDFYIELD(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),-0.0575,84.5,100,2,0)").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("ODDFYIELD(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),0.0575,84.5,100,2,5)").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("ODDFYIELD(DATE(2009,3,2),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),0.0575,84.5,100,2,0)").startswith("LOCAL-REJECT:"))

    def test_part_c_pathitem_type(self) -> None:
        # Numeric type 1 and INTEGER keyword
        self.assertEqual(dax.local('PATHITEM("1|2|3", 1, 1)&"z"'), "1z")
        self.assertEqual(dax.local('PATHITEM("1|2|3", 1, INTEGER)&"z"'), "1z")
        self.assertEqual(dax.local('PATHITEMREVERSE("1|2|3", 1, 1)&"z"'), "3z")
        self.assertEqual(dax.local('PATHITEMREVERSE("1|2|3", 1, INTEGER)&"z"'), "3z")
        self.assertEqual(dax.local('PATHITEM("1|2|3", 2, INTEGER)&"z"'), "2z")
        self.assertEqual(dax.local('PATHITEMREVERSE("1|2|3", 2, INTEGER)&"z"'), "2z")

        # Type 0 and TEXT keyword
        self.assertEqual(dax.local('PATHITEM("1|2|3", 1, 0)&"z"'), "1z")
        self.assertEqual(dax.local('PATHITEM("1|2|3", 1, TEXT)&"z"'), "1z")
        self.assertEqual(dax.local('PATHITEMREVERSE("1|2|3", 1, 0)&"z"'), "3z")
        self.assertEqual(dax.local('PATHITEMREVERSE("1|2|3", 1, TEXT)&"z"'), "3z")

        # Out-of-bounds positions return BLANK() -> "&z" gives "z"
        self.assertEqual(dax.local('PATHITEM("1|2|3", 5, INTEGER)&"z"'), "z")
        self.assertEqual(dax.local('PATHITEM("1|2|3", -1, INTEGER)&"z"'), "z")
        self.assertEqual(dax.local('PATHITEMREVERSE("1|2|3", 5, INTEGER)&"z"'), "z")

        # Type mismatch when string cannot be converted to integer with type INTEGER
        self.assertTrue(dax.local('PATHITEM("a|b|c|d", 1, 1)&"z"').startswith("LOCAL-REJECT:The following system error occurred: Type mismatch."))
        self.assertTrue(dax.local('PATHITEM("a|b|c|d", 1, INTEGER)&"z"').startswith("LOCAL-REJECT:The following system error occurred: Type mismatch."))

    def test_part_a_xirr(self) -> None:
        # Empty table
        self.assertEqual(
            dax.local('XIRR(FILTER(DATATABLE("v",DOUBLE,"d",DATETIME,{{-1,"2020-01-01"}}),FALSE()),[v],[d])'),
            "LOCAL-REJECT:A result for XIRR couldn't be determined because the Values and Dates arguments are empty."
        )

        # Same dates error
        self.assertEqual(
            dax.local('XIRR(DATATABLE("v",DOUBLE,"d",DATETIME,{{-100,"2020-01-01"},{110,"2020-01-01"}}),[v],[d])'),
            "LOCAL-REJECT:There isn't a valid result for the XIRR function for the given values."
        )

        # No sign change (all positive) -> couldn't find a solution
        self.assertEqual(
            dax.local('XIRR(DATATABLE("v",DOUBLE,"d",DATETIME,{{2027.02,"2021-03-16"},{13.75,"2021-06-18"},{251.08,"2021-08-10"}}),[v],[d])'),
            "LOCAL-REJECT:The XIRR function couldn't find a solution."
        )
        # ISERROR catches couldn't find a solution
        self.assertEqual(
            dax.local('ISERROR(XIRR(DATATABLE("v",DOUBLE,"d",DATETIME,{{2027.02,"2021-03-16"},{13.75,"2021-06-18"},{251.08,"2021-08-10"}}),[v],[d]))'),
            "True"
        )
        # Alternate result returned when no solution
        self.assertEqual(
            dax.local('XIRR(DATATABLE("v",DOUBLE,"d",DATETIME,{{2027.02,"2021-03-16"},{13.75,"2021-06-18"},{251.08,"2021-08-10"}}),[v],[d],0.3,5)'),
            "5"
        )
        # Zero flows with only one sign -> no solution
        self.assertEqual(
            dax.local('XIRR(DATATABLE("v",DOUBLE,"d",DATETIME,{{-100,"2020-01-01"},{0,"2021-01-01"}}),[v],[d])'),
            "LOCAL-REJECT:The XIRR function couldn't find a solution."
        )


if __name__ == "__main__":
    unittest.main()
