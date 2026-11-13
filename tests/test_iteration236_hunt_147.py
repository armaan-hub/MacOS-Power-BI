"""Task 147 (dax-hunt-147): fresh Power BI hunt, batch 5. Exact assertions per family, values copied from the measured Power BI answers.

Family A: CEILING / FLOOR / ISO.CEILING take the quotient number / significance as a double, rounded to 15 significant digits
(keeping any fraction), then the whole, times the significance. This applies to every integer significance below 2^53.
Family B: a multi-column table in a value position of IF / IF.EAGER / SWITCH / IFERROR is a query error at compile time, even in a
branch never read (IFERROR does not catch it). A date-producing scalar (DATE(...)) as the first argument of a time-intelligence
function is the same kind of error.
Known limits left alone (still differ in the spec): COSH, COS, COT, ACOTH, T.DIST.*, CONFIDENCE.NORM, POISSON.DIST, NORM.S.DIST, FV.
Not done: IF(TRUE(),1,ALL(Facts[Region])) = 1 is still refused, by the measure-level table gate (it was refused before this task too).
"""

import unittest

from tools.dax_oracle_diff import local


class TestIteration236Hunt147(unittest.TestCase):
    # Family A: the rounding is taken at 15 significant digits of the quotient
    def test_family_a_ceiling_floor_quotient_rounded_to_15_digits(self):
        self.assertEqual(local("CEILING(-1E15,-3)"), "-999999999999999")
        self.assertEqual(local("CEILING(1E15,3)"), "999999999999999")
        self.assertEqual(local("CEILING(-1E15,3)"), "-999999999999999")
        self.assertEqual(local("FLOOR(-1E15,-3)"), "-999999999999999")
        self.assertEqual(local("FLOOR(1E15,3)"), "999999999999999")
        self.assertEqual(local("FLOOR(-1E15,3)"), "-999999999999999")
        self.assertEqual(local("CEILING(-1E15,-7)"), "-1000000000000001")
        self.assertEqual(local("CEILING(-1E15,-2)"), "-1000000000000000")
        self.assertEqual(local("CEILING(-1E15,-4)"), "-1000000000000000")
        self.assertEqual(local("CEILING(-1E15,-0.3)"), "-999999999999999")
        self.assertEqual(local("ISO.CEILING(-1E15,3)"), "-999999999999999")
        self.assertEqual(local("CEILING(-999999999999998,-3)"), "-999999999999999")
        self.assertEqual(local("CEILING(-1E16,-3)"), "-9999999999999990")
        self.assertEqual(local("CEILING(-2E15,-3)"), "-2000000000000001")
        self.assertEqual(local("CEILING(10000000000000000,3)"), "9999999999999990")
        self.assertEqual(local("FLOOR(10000000000000001,3)"), "9999999999999990")
        self.assertEqual(local("FLOOR(-10000000000000001,-3)"), "-9999999999999990")
        self.assertEqual(local("CEILING(-9E15,-3)"), "-9000000000000000")

    def test_family_a_integer_quotients_snap_between_1e14_and_1e15(self):
        self.assertEqual(local("CEILING(-300000000000001,-3)"), "-300000000000000")
        self.assertEqual(local("CEILING(300000000000001,3)"), "300000000000000")
        self.assertEqual(local("FLOOR(300000000000002,3)"), "300000000000003")
        self.assertEqual(local("FLOOR(-300000000000002,-3)"), "-300000000000003")
        self.assertEqual(local("CEILING(-600000000000001,-3)"), "-600000000000000")
        self.assertEqual(local("CEILING(600000000000001,3)"), "600000000000000")
        self.assertEqual(local("FLOOR(600000000000002,3)"), "600000000000003")
        self.assertEqual(local("FLOOR(-600000000000002,-3)"), "-600000000000003")
        self.assertEqual(local("CEILING(-750000000000001,-3)"), "-750000000000000")
        self.assertEqual(local("CEILING(750000000000001,3)"), "750000000000000")
        self.assertEqual(local("FLOOR(750000000000002,3)"), "750000000000003")
        self.assertEqual(local("CEILING(-840000000000001,-3)"), "-840000000000000")
        self.assertEqual(local("FLOOR(-840000000000002,-3)"), "-840000000000003")
        self.assertEqual(local("CEILING(-930000000000001,-3)"), "-930000000000000")
        self.assertEqual(local("FLOOR(930000000000002,3)"), "930000000000003")
        self.assertEqual(local("CEILING(-1020000000000001,-3)"), "-1020000000000000")
        self.assertEqual(local("FLOOR(-1020000000000002,-3)"), "-1020000000000003")
        self.assertEqual(local("CEILING(1050000000000001,3)"), "1050000000000000")
        self.assertEqual(local("CEILING(-1200000000000001,-3)"), "-1200000000000000")
        self.assertEqual(local("FLOOR(-3000000000000002,-3)"), "-3000000000000000")
        self.assertEqual(local("CEILING(3000000000000001,3)"), "3000000000000000")
        self.assertEqual(local("CEILING(2100000000000001,7)"), "2100000000000000")
        self.assertEqual(local("CEILING(7000000000000001,7)"), "7000000000000000")
        self.assertEqual(local("CEILING(1000000000000001,3)"), "1000000000000002")
        self.assertEqual(local("ISO.CEILING(300000000000001,3)"), "300000000000000")
        self.assertEqual(local("CEILING(300000000000001,3)+0"), "300000000000000")
        self.assertEqual(local("CEILING(900000000000001,3)+0"), "900000000000000")

    def test_family_a_not_snapped_keeps_the_fraction_digits(self):
        self.assertEqual(local("CEILING(-1E14,-3)"), "-100000000000002")
        self.assertEqual(local("CEILING(-1E13,-3)"), "-10000000000002")
        self.assertEqual(local("CEILING(-100000000000001,-3)"), "-100000000000002")
        self.assertEqual(local("CEILING(-1000000000000001,-3)"), "-1000000000000002")
        self.assertEqual(local("CEILING(-5E14,-3)"), "-500000000000001")
        self.assertEqual(local("CEILING(-123456789012345,-7)"), "-123456789012347")
        self.assertEqual(local("FLOOR(1E14-0.1,1)"), "99999999999999")
        self.assertEqual(local("CEILING(1E14+0.1,1)"), "100000000000000")

    def test_family_a_mround_and_roundup_stay_exact(self):
        self.assertEqual(local("MROUND(300000000000001,3)"), "300000000000000")
        self.assertEqual(local("MROUND(900000000000001,3)"), "900000000000000")
        self.assertEqual(local("MROUND(3000000000000001,3)"), "3000000000000000")
        self.assertEqual(local("ROUNDUP(300000000000001/3,0)"), "100000000000000")
        self.assertEqual(local("ROUNDUP(900000000000001/3,0)"), "300000000000000")

    # Family B: a multi-column table in a value position is refused when the expression is compiled
    def test_family_b_multi_column_table_in_value_position_is_refused(self):
        for expression in (
            'IF(1=1,"x",Facts)',
            'IF(TRUE(),1,ROW("a",1,"b",2))',
            'IFERROR(1,{(1,2)})',
            'SWITCH(TRUE(),TRUE(),1,ROW("a",1,"b",2))',
            'IFERROR(1,TOPN(1,Facts))',
            'IFERROR(1,ALL(Facts))',
        ):
            with self.subTest(expression=expression):
                self.assertTrue(local(expression).startswith("LOCAL-"), local(expression))

    def test_family_b_one_column_and_two_column_row_shapes_stay_legal(self):
        self.assertEqual(local("IFERROR(1,{1,2})"), "1")
        self.assertEqual(local("IFERROR(1,CALENDAR(1,2))"), "1")
        self.assertEqual(local("IF(TRUE(),1,GENERATESERIES(1,2))"), "1")
        self.assertEqual(local('IFERROR(SUM(Facts[Sales]),ROW("a",1))'), "31.5")

    def test_family_b_time_intelligence_scalar_first_argument_is_refused(self):
        for function in ("DATESMTD", "DATESQTD", "DATESYTD", "PREVIOUSMONTH", "FIRSTDATE", "LASTDATE", "ENDOFMONTH"):
            for wrapper in ("IF(TRUE(),1,{})", "IFERROR(1,{})", "SWITCH(1,1,2,{})"):
                expression = wrapper.format(f"{function}(DATE(2020,1,1))")
                with self.subTest(expression=expression):
                    self.assertTrue(local(expression).startswith("LOCAL-"), local(expression))


if __name__ == "__main__":
    unittest.main()
