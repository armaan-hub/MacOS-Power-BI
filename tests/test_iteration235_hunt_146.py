"""Task 146 (dax-hunt-146): fresh Power BI hunt, batch 4. Exact assertions per family, values copied from the measured Power BI answers.

Family B: a NETWORKDAYS weekend outside 1..7 and 11..17 is a query-level refusal (IFERROR cannot catch it); fractions round half up.
Not done (tried, reverted, reported): family A (a whole number plus a 1E15 Double literal; a refusal broke 15 locked answers inside
MIN/MAX/ISNUMBER/IFERROR), family C (a |x| > 200 threshold for SIN/COS/TAN/COT contradicts locked answers such as SIN(DATE(2020,1,1))),
and family D (LN as a binary double breaks the locked EXP(LN(3))/3-1 and EXP(LN(7))/7-1 rows, which need EXP in doubles too).
Also not done: the trig and BETA last-digit rows with |x| <= 200, TAN(EXP(2)), COSH(5), BETA.DIST (known limits).
"""

import unittest
from decimal import Context, Decimal

from tools.dax_oracle_diff import local

_FIFTEEN = Context(prec=15)


def same15(text: str, expected: str) -> bool:
    """Equal at 15 significant digits, with the same sign (the hunt's rule for numbers)."""
    if text.startswith("LOCAL-"):
        return False
    local_value = Decimal(text)
    if repr(float(text)) == text:  # a shortest float repr stands for its exact binary double (the scorer's rule)
        local_value = Decimal(float(text))
    return _FIFTEEN.plus(local_value) == _FIFTEEN.plus(Decimal(expected)) and local_value.is_signed() == Decimal(expected).is_signed()


class TestIteration235Hunt146(unittest.TestCase):
    # Family A: not changed (see the module docstring). A whole number plus a whole number stays whole.
    def test_family_a_whole_plus_whole_stays_integer(self):
        self.assertEqual(local("1000000000000225+0"), "1000000000000225")

    # Family B: NETWORKDAYS weekend codes; a fraction rounds half up; an out-of-range or text weekend is refused
    def test_family_b_networkdays_fraction_rounds_half_up(self):
        self.assertEqual(local('IFERROR(NETWORKDAYS(DATE(2024,1,1),DATE(2024,3,1),1.5),"E")'), "44")
        self.assertEqual(local('IFERROR(NETWORKDAYS(DATE(2024,1,1),DATE(2024,3,1),11.5),"E")'), "52")
        self.assertEqual(local('IFERROR(NETWORKDAYS(DATE(2024,1,1),DATE(2024,3,1),7),"E")'), "44")

    def test_family_b_networkdays_out_of_range_weekend_refused(self):
        for weekend in ("0", "8", "10", "18", "-1", "BLANK()"):
            with self.subTest(weekend=weekend):
                self.assertTrue(local(f'IFERROR(NETWORKDAYS(DATE(2024,1,1),DATE(2024,3,1),{weekend}),"E")').startswith("LOCAL-REJECT"))
        self.assertTrue(local("NETWORKDAYS(DATE(2024,12,31),DATE(9999,12,31),0)").startswith("LOCAL-REJECT"))

    def test_family_b_networkdays_text_weekend_kept(self):
        # locked answers (dax_battery_misc) show text weekends answered; the spec's "1" text gives 45, as the numeric weekend 1 does
        self.assertEqual(local('IFERROR(NETWORKDAYS(DATE(2024,1,1),DATE(2024,3,1),"1"),"E")'), "45")

    # Family C: NOT refused. A threshold at |x| > 200 contradicts locked Power BI answers (SIN(DATE(2020,1,1)) is answered
    # correctly in the locked batteries), so the trig rows beyond 200 stay open. Only the answers within 200 are checked here.
    def test_family_c_trig_within_200_still_answered(self):
        self.assertFalse(local("SIN(57.1)").startswith("LOCAL-"))  # a known last-digit row, so only the answer is checked here
        self.assertFalse(local("COS(10.3)").startswith("LOCAL-"))

    # Family D: not changed (see the module docstring); EXP(LN(6)) = 6 holds with the Decimal LN
    def test_family_d_exp_ln_still_six(self):
        self.assertTrue(same15(local("EXP(LN(6))"), "6"))


if __name__ == "__main__":
    unittest.main()
