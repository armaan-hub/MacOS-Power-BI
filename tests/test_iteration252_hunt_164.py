"""Task 164 (dax-hunt-164): fresh-probe wrong answers, batch 21.

Family A: ROUND(x,0) of a whole number from 1E14 up to 1E16 keeps 15 significant digits, a tie toward zero
(ROUND(2.5E15+5,0) is 2.5E+15, ROUND(999999999999999.5,0) is 999999999999999, ROUND(1234567890123456,0) is 1234567890123460).
Family B: FIXED from 1E14 and FORMAT from 1E14 show a number at 15 significant digits, a tie half up (FORMAT(9.99E14+0.5,"0") is 999000000000001).
Family C: an IF with a text-literal condition that cannot read as True/False fails the query when it is evaluated, and ISERROR does not catch it.
Family D: not changed (see the report): a top-level normalization conflicts with an existing locked 28-digit Decimal test.
Values copied from the measured Power BI answers (2026-11-15).
"""

import unittest

from tools.dax_oracle_diff import local


class TestIteration252Hunt164(unittest.TestCase):
    def test_family_a_whole_round_keeps_fifteen_digits(self):
        self.assertEqual(local('ROUND(1234567890123456,0)&"z"'), "1234567890123460z")
        self.assertEqual(local('ROUND(2.5E15+5,0)&"z"'), "2.5E+15z")
        self.assertEqual(local('ROUND(4.5E15+15,0)&"z"'), "4.50000000000001E+15z")
        self.assertEqual(local('ROUND(9007199254740991,0)&"z"'), "9007199254740990z")
        self.assertEqual(local('ROUND(999999999999999.5,0)&"z"'), "999999999999999z")
        self.assertEqual(local('ROUND(-2.5E15-5,0)&"z"'), "-2.5E+15z")
        self.assertEqual(local('ROUND(INT(1E15+1),0)&"z"'), "1000000000000000z")

    def test_family_a_existing_round_shapes_unchanged(self):
        self.assertEqual(local('ROUND(2.5,0)&"z"'), "3z")
        self.assertEqual(local('ROUND(0.5,0)&"z"'), "1z")
        self.assertEqual(local('ROUND(-0.5,0)&"z"'), "-1z")
        self.assertEqual(local('ROUND(999999999999999.4,0)&"z"'), "999999999999999z")
        self.assertEqual(local('ROUND(12345678901234.5,0)&"z"'), "12345678901235z")
        self.assertEqual(local('ROUND(1E15+1,0)&"z"'), "1E+15z")

    def test_family_b_fixed_from_1e14_shows_fifteen_digits(self):
        self.assertEqual(local("FIXED(9.99E14+0.5,3)"), "999,000,000,000,001.000")
        self.assertEqual(local("FIXED(9.99E14+0.5,3,1)"), "999000000000001.000")
        self.assertEqual(local("FIXED(1.5E14+0.25,3)"), "150,000,000,000,000.000")
        self.assertEqual(local("FIXED(999999999999999.5,3)"), "1,000,000,000,000,000.000")
        self.assertEqual(local("FIXED(CURRENCY(1E14)+0.5,3)"), "100,000,000,000,001.000")
        self.assertEqual(local("FIXED(CURRENCY(1E14)+0.5,3,1)"), "100000000000001.000")

    def test_family_b_fixed_below_1e14_unchanged(self):
        self.assertEqual(local("FIXED(12345678901234.56,2)"), "12,345,678,901,234.56")

    def test_family_b_format_from_1e14_shows_fifteen_digits(self):
        self.assertEqual(local('FORMAT(9.99E14+0.5,"#,0.000")'), "999,000,000,000,001.000")
        self.assertEqual(local('FORMAT(9.99E14+0.5,"0")'), "999000000000001")
        self.assertEqual(local('FORMAT(CURRENCY(1E14)+0.5,"#,0.000")'), "100,000,000,000,001.000")
        self.assertEqual(local('FORMAT(CURRENCY(1E14)+0.5,"0")'), "100000000000001")

    def test_family_b_format_whole_numbers_below_1e15_exact(self):
        self.assertEqual(local('FORMAT(100000000000000,"0")'), "100000000000000")
        self.assertEqual(local('FORMAT(123456789012345,"0")'), "123456789012345")

    def test_family_c_evaluated_text_literal_if_is_not_caught_by_iserror(self):
        # Power BI: "Cannot convert value 'a' of type Text to type True/False" (the whole query fails, measured)
        for expression in (
            'ISERROR(IF("a",IF(ISBLANK(SUM(Facts[Sales])),CURRENCY(1.23456),"1.5"),"abc"))',
            'IF("a",1,2)',
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT"), expression)

    def test_family_c_constant_text_if_is_caught_by_iserror(self):
        # Power BI (locked battery dax_battery_textnum19_extra): ISERROR(IF("abc",1,2)) and ISERROR(IF(" ",1,2)) are True
        self.assertEqual(local('ISERROR(IF("abc",1,2))'), "True")
        self.assertEqual(local('ISERROR(IF(" ",1,2))'), "True")

    def test_family_c_text_conditions_that_read_as_logicals_are_kept(self):
        self.assertEqual(local('IF("TRUE",1,2)'), "1")
        self.assertEqual(local('IF("1",1,2)'), "1")
        self.assertEqual(local('IF("False",1,2)'), "2")
        self.assertEqual(local('ISERROR(IF("TRUE",1,2))'), "False")
        self.assertEqual(local('IFERROR(IF("1",1,2),"E")'), "1")

    def test_family_c_untaken_or_eager_text_if_inside_iferror_unchanged(self):
        # measured: the SWITCH branch that is not taken never runs its IF("a"), and IFERROR catches IF.EAGER("a",..) (E)
        self.assertEqual(local('IFERROR(IF.EAGER("a",-2.5,7),"E")'), "E")
        self.assertEqual(local('ISNONTEXT(IF(TRUE(),MAX(Facts[Region]),IF("a","abc","abc")))'), "False")

    def test_family_d_decimal_results_keep_their_digits(self):
        self.assertEqual(local("1.5+2"), "3.5")


if __name__ == "__main__":
    unittest.main()
