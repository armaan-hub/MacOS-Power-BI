"""Iteration 117: logical-blank-17 (logical operator's BLANK beside other values).

Plan: docs/plans/2026-11-03-logical-blank-17.md
Spec: tools/parity/task27_logical_blank_spec.json
"""
from __future__ import annotations

import unittest
from tools import dax_oracle_diff as dax


class LogicalBlank17PartATest(unittest.TestCase):
    def test_conditional_logical_blanks(self) -> None:
        """IF, SWITCH, COALESCE with logical blank branches evaluate to BLANK, not FALSE."""
        self.assertEqual("BLANK", dax.local('IF(TRUE(),2.5&&"",2.5&&"")'))
        self.assertEqual("BLANK", dax.local('IF(TRUE(),2.5&&"",OR(0,""))'))
        self.assertEqual("BLANK", dax.local('SWITCH(1,1,2.5&&"",2.5&&"")'))
        self.assertEqual("BLANK", dax.local('COALESCE(2.5&&"",OR(0,""))'))
        self.assertEqual("BLANK", dax.local('IF.EAGER(TRUE(),2.5&&"",OR(0,""))'))

    def test_strict_equal_logical_blank(self) -> None:
        """Strict equality (==) does not coerce a logical BLANK to FALSE."""
        self.assertEqual("True", dax.local('IF(TRUE(),2.5&&"")==BLANK()'))
        self.assertEqual("True", dax.local('IF(TRUE(),OR(0,""))==BLANK()'))
        self.assertEqual("False", dax.local('IF(TRUE(),2.5&&"")==FALSE()'))
        self.assertEqual("False", dax.local('IF(TRUE(),OR(0,""))==FALSE()'))

    def test_islogical_over_conditionals(self) -> None:
        """ISLOGICAL is True if all branches are pure boolean BLANKs, False if any branch has un-folded text."""
        self.assertEqual("True", dax.local('ISLOGICAL(IF(TRUE(),2.5&&"",2.5&&""))'))
        self.assertEqual("True", dax.local('ISLOGICAL(IF(TRUE(),2.5&&"",OR(0,"")))'))
        self.assertEqual("False", dax.local('ISLOGICAL(IF(TRUE(),2.5&&"","0"||LEFT("a",0)))'))
        self.assertEqual("False", dax.local('ISLOGICAL(IF(FALSE(),2.5&&"","0"||LEFT("a",0)))'))


class LogicalBlank17PartBTest(unittest.TestCase):
    def test_tableconstructor_logical_blank_beside_text(self) -> None:
        """In a table constructor, a logical BLANK beside text becomes an empty string."""
        self.assertEqual("4", dax.local('SUMX({2.5&&"","a"},IF(ISBLANK([Value]),1,2))'))
        self.assertEqual("3", dax.local('SUMX({2.5&&"","a"},IF([Value]=BLANK(),1,2))'))
        self.assertEqual("4", dax.local('SUMX({2.5&&"","a"},IF([Value]==BLANK(),1,2))'))
        self.assertEqual("1", dax.local('SUMX({2.5&&"","a"},LEN([Value]))'))
        self.assertEqual("4", dax.local('SUMX({2.5&&"","a"},IF(ISLOGICAL([Value]),1,2))'))

    def test_tableconstructor_logical_blank_beside_date(self) -> None:
        """In a table constructor, a logical BLANK beside date becomes day zero (12/30/1899)."""
        self.assertEqual("12/30/1899 00:00:00", dax.local('MINX({2.5&&"",DATE(2020,1,1)},[Value])'))
        self.assertEqual("01/01/2020 00:00:00", dax.local('MAXX({2.5&&"",DATE(2020,1,1)},[Value])'))
        self.assertEqual("2", dax.local('COUNTX({2.5&&"",DATE(2020,1,1)},[Value])'))
        self.assertEqual("2", dax.local('COUNTAX({2.5&&"",DATE(2020,1,1)},[Value])'))
        self.assertEqual("True", dax.local('ISDATETIME(MAXX({2.5&&"",DATE(2020,1,1)},[Value]))'))

    def test_arithmetic_logical_blank_stays_refused(self) -> None:
        """Unsettled arithmetic with logical BLANK beside text or error stays safely refused."""
        self.assertEqual("BLANK", dax.local('IFERROR(((1&&""))*"a",7)'))  # Power BI 2026-11-03 (Task 37)


if __name__ == "__main__":
    unittest.main()
