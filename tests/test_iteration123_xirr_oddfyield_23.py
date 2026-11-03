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


    def test_part_a_xirr_iterative_answers(self) -> None:
        # Power BI stops its bracketing bisection early, so its answers are not the exact roots (live answers, Task 33 review).
        six = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-4461.19,"2019-12-09"},{925.15,"2020-04-22"},{912.93,"2020-07-21"},{1952.23,"2021-09-07"},{1781.96,"2022-07-18"},{1870.07,"2022-08-28"}})'
        for tail, expected in (("", "0.335566799342633"), (",-0.5", "0.3355667963624"), (",0.3,5", "0.335566798597574")):
            self.assertTrue(same(expected, dax.local(f"XIRR({six},[v],[d]{tail})")), tail)
        leap = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-100,"2020-01-01"},{BLANK(),"2020-02-01"},{110,"2021-01-01"}})'
        self.assertTrue(same("0.0997135788202284", dax.local(f"XIRR({leap},[v],[d])")))
        # first flow is not the earliest date: Power BI sorts by date first
        unsorted = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-2055.96,"2023-01-24"},{-30.74,"2022-03-18"},{1932.99,"2021-07-08"},{1183.52,"2022-05-12"},{1899.83,"2021-02-23"},{462.16,"2019-01-18"},{1562.93,"2020-07-31"},{-204.85,"2021-10-12"}})'
        self.assertTrue(same("-0.506473898520926", dax.local(f"XIRR({unsorted},[v],[d])")))
        # a sign change in the flows but no root in the searched range: error, or the alternate result
        no_root = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-2273.94,"2020-09-15"},{126.5,"2021-12-10"},{-46.8,"2022-02-10"},{-224.3,"2022-09-10"}})'
        self.assertEqual(dax.local(f"XIRR({no_root},[v],[d])"), "LOCAL-REJECT:The XIRR function couldn't find a solution.")
        self.assertEqual(dax.local(f"XIRR({no_root},[v],[d],0.3,5)"), "5")
        self.assertEqual(dax.local(f"ISERROR(XIRR({no_root},[v],[d]))"), "True")
        # a root at 1 + rate = 2.5e-9 is outside what was measured: stays refused, never guessed
        deep = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-3196.7,"2019-04-06"},{1269.18,"2019-11-14"},{-164.01,"2021-07-19"},{95.31,"2021-07-29"}})'
        self.assertTrue(dax.local(f"XIRR({deep},[v],[d])").startswith("LOCAL-REJECT:"))

    def test_part_a_xirr_several_roots_on_one_side_refused(self) -> None:
        # Live Power BI (Task 33 fresh review): with several roots on one side of the guess its pick is unsettled, so we refuse.
        # Power BI said "couldn't find a solution" for the first and -0.894808008519976 for the second (we used to say -0.643... and 0.2799...).
        first = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-4122.65,"2021-09-16"},{243.16,"2021-09-30"},{2441.01,"2021-05-09"},{-1719.01,"2020-03-21"},{807.7,"2021-06-14"},{4698.24,"2020-05-08"},{393.04,"2022-04-12"},{966.44,"2019-01-25"}})'
        second = 'DATATABLE("v",DOUBLE,"d",DATETIME,{{-7460.3,"2021-01-30"},{2638.28,"2020-01-25"},{-3318.55,"2020-10-21"},{4134.2,"2022-04-20"},{1178.31,"2022-08-15"},{4807.3,"2021-08-24"},{-736.0,"2023-04-22"}})'
        for table in (first, second):
            self.assertTrue(dax.local(f"XIRR({table},[v],[d])").startswith("LOCAL-REJECT:"), table)
        self.assertTrue(dax.local(f"ISERROR(XIRR({first},[v],[d]))").startswith("LOCAL-REJECT:"))


if __name__ == "__main__":
    unittest.main()
