"""Iteration 254: Task 166 (dax-hunt-166), Student-t, chi-square and percentile last digits, batch 23.

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


class TestIteration254Hunt166(unittest.TestCase):
    def test_family_a_df2_right_and_two_tailed_tails_are_stable(self) -> None:
        # the right tail and the two-tailed value of df 2 keep their last digits at large t (the cancellation-free form)
        self.assertTrue(same15("0.00492622851166285", dax.local("T.DIST.RT(10,2)")))
        self.assertTrue(same15("4.99925012497813E-05", dax.local("T.DIST.RT(100,2)")))
        self.assertTrue(same15("9.999999999985E-13", dax.local("T.DIST.2T(1E6,2)")))
        self.assertTrue(same15("1E-30", dax.local("T.DIST.2T(1E15,2)")))
        self.assertTrue(same15("1E-30", dax.local("T.DIST.2T(ABS(1E15),2)")))

    def test_family_a_df2_rows_that_already_matched_stay_exact(self) -> None:
        self.assertTrue(same15("0.0477329831333546", dax.local("T.DIST.RT(3,2)")))
        self.assertTrue(same15("0.136196562445501", dax.local("T.DIST.RT(1.5,2)")))
        self.assertTrue(same15("0.183503419072274", dax.local("T.DIST.2T(2,2)")))
        self.assertTrue(same15("0.0917517095361369", dax.local("T.DIST(-2,2,TRUE())")))

    def test_family_a_inverse_rows_fixed_by_newton_on_the_tail(self) -> None:
        self.assertTrue(same15("0.267180865704146", dax.local("T.INV(0.6,5)")))
        self.assertTrue(same15("2.22813885198627", dax.local("T.INV.2T(0.05,10)")))

    def test_family_b_chisq_inverse_fixed_by_newton(self) -> None:
        self.assertTrue(same15("0.584374374155183", dax.local("CHISQ.INV(0.1,3)")))

    def test_family_b_confidence_t_fixed_through_the_t_inverse(self) -> None:
        self.assertTrue(same15("0.901849296870862", dax.local("CONFIDENCE.T(0.25,1.5,5)")))

    @unittest.expectedFailure
    def test_known_limit_t_inverse_last_digits_df2(self) -> None:
        # known limit (measured): Power BI's T.INV differs from the correctly rounded value in the last digits at df 2
        self.assertTrue(same15("-6.96455673428328", dax.local("T.INV(0.01,2)")))

    @unittest.expectedFailure
    def test_known_limit_t_right_tail_df5(self) -> None:
        # known limit (measured): T.DIST.RT(10,5) is 8.54737878714819E-05 in Power BI, one ulp-scale digit away from the app
        self.assertTrue(same15("8.54737878714819E-05", dax.local("T.DIST.RT(10,5)")))

    @unittest.expectedFailure
    def test_known_limit_two_tailed_big_x_df5(self) -> None:
        # known limit (measured): T.DIST.2T(1E6,5) is 1.89803344909213E-29 in Power BI
        self.assertTrue(same15("1.89803344909213E-29", dax.local("T.DIST.2T(1E6,5)")))

    @unittest.expectedFailure
    def test_known_limit_right_tail_big_x_df10(self) -> None:
        # known limit (measured): T.DIST.RT(1E15,10) is 1.23046875000001E-146 in Power BI
        self.assertTrue(same15("1.23046875000001E-146", dax.local("T.DIST.RT(1E15,10)")))

    def test_family_c_out_of_range_percentile_exc_is_a_query_error(self) -> None:
        # Power BI raises the percentile range error; a bare call and a direct IFERROR both fail the query (the local engine refuses)
        self.assertTrue(dax.local("PERCENTILE.EXC(Facts[Quantity],0)").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local('IFERROR(PERCENTILE.EXC(Facts[Quantity],0),"E")').startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local('ISERROR(PERCENTILE.EXC(Facts[Quantity],0))').startswith("LOCAL-REJECT:"))

    @unittest.expectedFailure
    def test_known_limit_percentile_error_beside_a_catchable_error(self) -> None:
        # known limit (measured): Power BI returns the percentile query error here; the local engine's PERMUT(0,10) error is caught
        # first by IFERROR and gives "E" (evaluation order of a query-level error beside a catchable one is not modelled)
        self.assertTrue(dax.local('IFERROR(NORM.INV(0.5,PERMUT(0,10),PERCENTILE.EXC(Facts[Quantity],0)),"E")').startswith("LOCAL-REJECT:"))


if __name__ == "__main__":
    unittest.main()
