"""Iteration 134: Task 44 count-text-compare-34.

Tests for COUNTX/COUNTAX edge cases, text read as numbers or dates, and BLANK / mixed-type comparisons:
- Part A: COUNTX and COUNTAX over in-memory table constructors counting NaN, COUNTX of Booleans returning BLANK.
- Part B: Text read as numbers or dates ("1 1/2" as 37257 / 2002-01-01, "1,000" as 2000-01-01, TIMEVALUE of dates,
  DATEVALUE of times, invalid month in date text caught as runtime conversion error).
- Part C: Strict == comparisons involving BLANK() evaluating to False/True instead of raising type mismatch;
  cross-type comparisons with Variant expressions using DAX Variant ordering.
"""
import unittest

from tools import dax_oracle_diff as dax


class CountTextCompare34Tests(unittest.TestCase):
    def test_part_a_countx_countax_nan_and_booleans(self) -> None:
        # In-memory table constructors count NaN
        self.assertTrue(dax.same("1", dax.local('COUNTAX({1}, 0/0)')))
        self.assertTrue(dax.same("2", dax.local('COUNTX({1,2}, 0/0)')))
        self.assertTrue(dax.same("1", dax.local('COUNTAX(ROW("Value",1), 0/0)')))
        self.assertTrue(dax.same("1", dax.local('CALCULATE(COUNTAX({1}, 0/0))')))

        # COUNTX of Boolean evaluates to BLANK
        self.assertEqual("BLANK", dax.local('COUNTX({1,2}, SWITCH(TRUE(), 1=1, TRUE(), "a"))'))
        self.assertEqual("BLANK", dax.local('COUNTX({"a"}, IF(1=1, TRUE(), "a"))'))
        self.assertEqual("BLANK", dax.local('CALCULATE(COUNTX(Facts, IF(MAX(Facts[Quantity])>3, TRUE(), 7)), Facts[Region]<>"x")'))

    def test_part_b_text_read_as_number_or_date(self) -> None:
        # "1 1/2" parsed as date 1/1/2002 (serial 37257)
        self.assertTrue(dax.same("37257", dax.local('VALUE("1 1/2")')))
        self.assertTrue(dax.same("37257", dax.local('"1 1/2"+0')))
        self.assertEqual("01/01/2002 00:00:00", dax.local('DATEVALUE("1 1/2")'))
        self.assertEqual("01/01/2002 00:00:00", dax.local('CONVERT("1 1/2", DATETIME)'))

        # "1,000" parsed as date 1/1/2000
        self.assertEqual("01/01/2000 00:00:00", dax.local('DATEVALUE("1,000")'))
        self.assertEqual("01/01/2000 00:00:00", dax.local('CONVERT("1,000", DATETIME)'))

        # TIMEVALUE of date-only strings returns 12/30/1899 00:00:00
        self.assertEqual("12/30/1899 00:00:00", dax.local('TIMEVALUE("2020-01-02")'))
        self.assertEqual("12/30/1899 00:00:00", dax.local('TIMEVALUE("1/2/2020")'))
        self.assertEqual("12/30/1899 00:00:00", dax.local('TIMEVALUE("1,000")'))
        self.assertEqual("12/30/1899 00:00:00", dax.local('TIMEVALUE("1 1/2")'))

        # DATEVALUE of time-only strings returns 12/30/1899 00:00:00
        self.assertEqual("12/30/1899 00:00:00", dax.local('DATEVALUE("12:30")'))
        self.assertEqual("12/30/1899 00:00:00", dax.local('DATEVALUE("1:30 PM")'))
        self.assertEqual("12/30/1899 00:00:00", dax.local('DATEVALUE("3.5")'))

        # Out-of-range dates ("0/2/2020") raise runtime conversion error caught by ISERROR/IFERROR
        self.assertTrue(dax.same("1", dax.local('COUNTROWS(FILTER(Facts, ISERROR(VALUE(Facts[Quantity]&"/2/2020"))))')))
        self.assertTrue(dax.same("219470", dax.local('SUMX(Facts, IFERROR(VALUE(Facts[Quantity]&"/2/2020"), 7))')))

    def test_part_c_blank_and_variant_comparisons(self) -> None:
        # Strict == comparisons with BLANK()
        self.assertEqual("False", dax.local('VAR y=BLANK() RETURN y=="a"'))
        self.assertEqual("False", dax.local('VAR y=BLANK() RETURN y==""'))
        self.assertEqual("False", dax.local('VAR y=BLANK() RETURN y==TRUE()'))
        self.assertEqual("False", dax.local('VAR y=BLANK() RETURN y==FALSE()'))
        self.assertEqual("True", dax.local('VAR y=BLANK() RETURN y==OR(0,"")'))
        self.assertTrue(dax.same("4", dax.local('SUMX({"a","b"}, IF(VAR y=BLANK() RETURN y==[Value], 1, 2))')))
        self.assertTrue(dax.same("3", dax.local('SUMX({BLANK(),"a"}, IF(VAR y=BLANK() RETURN y==[Value], 1, 2))')))
        self.assertTrue(dax.same("1", dax.local('COUNTROWS(FILTER({BLANK(),"a"}, VAR y=BLANK() RETURN y==[Value]))')))

        # Variant cross-type comparisons
        self.assertTrue(dax.same("1", dax.local('CALCULATE(COUNTROWS(Facts), Facts[Sales]>=IF(1=2, 2, ""))')))
        self.assertEqual("BLANK", dax.local('COUNTROWS(CALCULATETABLE(Facts, Facts[Quantity]>VAR t="East" RETURN COALESCE(t, 0)))'))
        self.assertTrue(dax.same("6", dax.local('CALCULATE(COUNTROWS(Facts), Facts[Sales]<=VAR t="East" RETURN COALESCE(t, 0))')))
        self.assertTrue(dax.same("2", dax.local('IF(0>VAR t="East" RETURN COALESCE(t, 0), 1, 2)')))


if __name__ == "__main__":
    unittest.main()
