"""Iteration 255: Task 167 (dax-hunt-167), last digits and refusals for NOMINAL, RATE, COT, CHISQ.DIST.RT and NORM.S.DIST.

NOMINAL returns the double's shortest text (not its binary expansion) and RATE refuses the near-1E+67 root that the engine refuses.
COT, CHISQ.DIST.RT(x,1) and NORM.S.DIST(z,0) have no closed form that fits every measured row, so they stay on main.

Values are the Power BI answers measured for the spec rows (15 significant digits). Known limits that stay wrong are marked expectedFailure.
"""

import unittest
from decimal import Decimal
from tools import dax_oracle_diff as dax


def same15(pbi: str, loc: str) -> bool:
    # Power BI doubles are compared at 15 significant digits
    if loc.startswith("LOCAL-REJECT") or loc.startswith("E"):
        return False
    return Decimal(format(Decimal(float(loc)), ".15g")) == Decimal(pbi)  # the double's exact value, rounded (as the scorer does)


class TestIteration255Hunt167(unittest.TestCase):
    def test_nominal_returns_plain_double_text(self) -> None:
        # NOMINAL is a plain double: the result is the shortest text, not the binary expansion of the double
        self.assertEqual(dax.local("NOMINAL(0.1,2)"), "0.09761769634030282")
        self.assertNotIn("0.097617696340302817", dax.local("NOMINAL(0.1,2)"))

    def test_nominal_rows_that_match_stay_exact(self) -> None:
        self.assertTrue(same15("0.096840346369101", dax.local("NOMINAL(0.1,3)")))
        self.assertTrue(same15("0.0964547563377804", dax.local("NOMINAL(0.1,4)")))
        self.assertTrue(same15("0.0956896851468452", dax.local("NOMINAL(0.1,12)")))
        self.assertTrue(same15("0.0490889377161565", dax.local("NOMINAL(0.05,4)")))
        self.assertTrue(same15("0.0682341000072446", dax.local("NOMINAL(0.07,4)")))

    @unittest.expectedFailure
    def test_known_limit_nominal_one_ulp_of_root(self) -> None:
        # known limit (measured): NOMINAL(0.1,2) is 0.0976176963403033 in Power BI, one root ulp away from the app
        self.assertTrue(same15("0.0976176963403033", dax.local("NOMINAL(0.1,2)")))

    @unittest.expectedFailure
    def test_known_limit_nominal_large_periods(self) -> None:
        # known limit (measured): NOMINAL(0.1,365) is 0.0953226247647621 in Power BI
        self.assertTrue(same15("0.0953226247647621", dax.local("NOMINAL(0.1,365)")))

    def test_rate_refuses_when_pv_and_fv_are_zero(self) -> None:
        # Power BI refuses a rate with no present or future value (too large); measured rows
        self.assertTrue(dax.local("RATE(0.5,-0.5,0)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("RATE(0.25,-1,0)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("RATE(2,-0.5,0)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("RATE(0.3,-0.3,0,0,1)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("RATE(0.5,1,0)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("RATE(0.7,-1,0)").startswith("LOCAL-REJECT"))

    def test_rate_large_rates_stay_exact(self) -> None:
        # measured Power BI answers for large rates (no cap on the rate)
        self.assertEqual(dax.local("RATE(1,-1E6,1)"), "999999")
        self.assertEqual(dax.local("RATE(1,-2E6,1)"), "1999999")
        self.assertEqual(dax.local("RATE(1,-1E7,1)"), "9999999")
        self.assertEqual(dax.local("RATE(1,-1E9,1)"), "999999999")
        self.assertEqual(dax.local("RATE(1,-1E12,1)"), "999999999999")
        self.assertEqual(dax.local("RATE(1,-1,1E-7)"), "9999999")
        self.assertEqual(dax.local("RATE(1,-2E6,1,0,0,1E6)"), "1999999")

    def test_rate_with_pv_stays_exact(self) -> None:
        self.assertTrue(same15("2.20871215252208", dax.local("RATE(0.5,-0.5,0.1)")))

    def test_rate_rows_that_match_stay_exact(self) -> None:
        self.assertTrue(same15("-0.203862224011488", dax.local("RATE(1.5,-1,2)")))
        self.assertTrue(same15("0.138382347169819", dax.local("RATE(2.5,-1,2)")))
        self.assertTrue(same15("1.94018520188674", dax.local("RATE(0.2,-1,0.1)")))

    def test_cot_rows_that_match_stay_exact(self) -> None:
        self.assertTrue(same15("0.642092615934331", dax.local("COT(1)")))
        self.assertTrue(same15("-7.01525255143454", dax.local("COT(3)")))
        self.assertTrue(same15("9.96664442325924", dax.local("COT(0.1)")))
        self.assertTrue(same15("99999.9999966667", dax.local("COT(1E-5)")))

    @unittest.expectedFailure
    def test_known_limit_cot_of_exp1_last_digit(self) -> None:
        # known limit (measured): COT(EXP(1)) is -2.21951178368118 in Power BI; the app's EXP(1) is one ulp off the engine's
        self.assertTrue(same15("-2.21951178368118", dax.local("COT(EXP(1))")))

    @unittest.expectedFailure
    def test_known_limit_cot_of_100_last_digit(self) -> None:
        # known limit (measured): COT(100) is -1.70295691942647 in Power BI
        self.assertTrue(same15("-1.70295691942647", dax.local("COT(100)")))

    def test_chisq_dist_rt_df1_rows_that_match_stay_exact(self) -> None:
        self.assertTrue(same15("0.751829634045849", dax.local("CHISQ.DIST.RT(0.1,1)")))
        self.assertTrue(same15("0.479500122186953", dax.local("CHISQ.DIST.RT(0.5,1)")))
        self.assertTrue(same15("0.920344325445942", dax.local("CHISQ.DIST.RT(0.01,1)")))

    @unittest.expectedFailure
    def test_known_limit_chisq_dist_rt_df1_last_digit(self) -> None:
        # known limit (measured): CHISQ.DIST.RT(3,1) is 0.0832645166635504 in Power BI, the app ends in ...49
        self.assertTrue(same15("0.0832645166635504", dax.local("CHISQ.DIST.RT(3,1)")))

    def test_norm_s_dist_density_rows_that_match_stay_exact(self) -> None:
        self.assertTrue(same15("0.396952547477012", dax.local("NORM.S.DIST(0.1,0)")))
        self.assertTrue(same15("0.0539909665131881", dax.local("NORM.S.DIST(2,0)")))
        self.assertTrue(same15("0.00443184841193801", dax.local("NORM.S.DIST(3,0)")))

    @unittest.expectedFailure
    def test_known_limit_norm_s_dist_density_last_digit(self) -> None:
        # known limit (measured): NORM.S.DIST(0.5,0) is 0.352065326764299 in Power BI, the app ends in ...95
        self.assertTrue(same15("0.352065326764299", dax.local("NORM.S.DIST(0.5,0)")))
