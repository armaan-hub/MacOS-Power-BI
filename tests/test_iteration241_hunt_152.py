"""Task 152 (dax-hunt-152): fresh Power BI hunt, batch 10. Exact assertions copied from the measured Power BI answers.
Family A: a TIME or NOW result before 01/01/0100 is refused at top level as DATE(2020,1,1)-1E8 is (no OverflowError); its numeric
uses keep the real number, and its date parts are errors.
Family B: T.DIST (cumulative), T.DIST.RT and T.DIST.2T follow the measured precision rule: the centre value is exactly 0.5 (or 1 for
T.DIST.2T), and df 1 with |x| up to 0.5 is 0.5 + sign(x) * asin(sqrt(1 - b)) / pi with b = 1 / (1 + x*x).
"""
import unittest

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


class TestIteration241Hunt152(unittest.TestCase):
    # Family A: an out-of-range datetime from TIME or DATE is refused, not an OverflowError
    def test_family_a_out_of_range_is_refused(self):
        self.assertTrue(local("(TIME(13,5,0))-(123456789.123)").startswith("LOCAL-REJECT"), "(TIME(13,5,0))-(123456789.123)")
        self.assertTrue(local("TIME(13,5,0)-1E8").startswith("LOCAL-REJECT"), "TIME(13,5,0)-1E8")
        self.assertTrue(local("TIME(13,5,0)-1E15").startswith("LOCAL-REJECT"), "TIME(13,5,0)-1E15")
        self.assertTrue(local("TIME(1,0,0)-800000").startswith("LOCAL-REJECT"), "TIME(1,0,0)-800000")
        self.assertTrue(local("DATE(2020,1,1)-1E8").startswith("LOCAL-REJECT"), "DATE(2020,1,1)-1E8")
        self.assertTrue(local("DATE(2020,1,1)-1E15").startswith("LOCAL-REJECT"), "DATE(2020,1,1)-1E15")
        self.assertTrue(local("TIME(13,5,0)-1E8").startswith("LOCAL-REJECT"), "TIME(13,5,0)-1E8")
        self.assertTrue(local("YEAR(DATE(2020,1,1)-1E8)").startswith("LOCAL-REJECT"), "YEAR(DATE(2020,1,1)-1E8)")
        self.assertTrue(local("MONTH(DATE(2020,1,1)-1E8)").startswith("LOCAL-REJECT"), "MONTH(DATE(2020,1,1)-1E8)")
        self.assertTrue(local("DAY(DATE(2020,1,1)-1E8)").startswith("LOCAL-REJECT"), "DAY(DATE(2020,1,1)-1E8)")
        self.assertTrue(local("HOUR(TIME(13,5,0)-123456789.123)").startswith("LOCAL-REJECT"), "HOUR(TIME(13,5,0)-123456789.123)")

    def test_family_a_numeric_uses_stay_exact(self):
        self.assertTrue(_same_15("(DATE(2020,1,1)-1E8)*1", "-99956169"), "(DATE(2020,1,1)-1E8)*1")
        self.assertTrue(_same_15("INT(DATE(2020,1,1)-1E8)", "-99956169"), "INT(DATE(2020,1,1)-1E8)")
        self.assertTrue(_same_15("CONVERT(DATE(2020,1,1)-1E8,DOUBLE)", "-99956169"), "CONVERT(DATE(2020,1,1)-1E8,DOUBLE)")
        self.assertTrue(_same_15("(TIME(1,0,0)-800000)*1", "-799999.958333333"), "(TIME(1,0,0)-800000)*1")
        self.assertTrue(_same_15("(TIME(13,5,0)-1E8)*1", "-99999999.4548611"), "(TIME(13,5,0)-1E8)*1")

    def test_family_a_comparison(self):
        self.assertEqual(local("DATE(2020,1,1)-1E8>DATE(1900,1,1)"), "False")

    # Family B: T.DIST / T.DIST.RT / T.DIST.2T precision rule, values copied from the saved Power BI answers
    def test_family_b_t_dist_precision(self):
        self.assertTrue(_same_15("T.DIST(1E-15,0.5,TRUE())", "0.5"), "T.DIST(1E-15,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(-1E-15,0.5,TRUE())", "0.5"), "T.DIST(-1E-15,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-15,3,TRUE())", "0.5"), "T.DIST(1E-15,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-17,1,TRUE())", "0.5"), "T.DIST(1E-17,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(-1E-12,0.5,TRUE())", "0.5"), "T.DIST(-1E-12,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-10,0.5,TRUE())", "0.5"), "T.DIST(1E-10,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-15,10,TRUE())", "0.5"), "T.DIST(1E-15,10,TRUE())")
        self.assertTrue(_same_15("T.DIST.RT(1E-15,0.5)", "0.5"), "T.DIST.RT(1E-15,0.5)")
        self.assertTrue(_same_15("T.DIST.2T(1E-15,0.5)", "1"), "T.DIST.2T(1E-15,0.5)")
        self.assertTrue(_same_15("T.DIST(0,0.5,TRUE())", "0.5"), "T.DIST(0,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-9,0.5,TRUE())", "0.5"), "T.DIST(1E-9,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-8,0.5,TRUE())", "0.5"), "T.DIST(1E-8,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(3E-8,0.5,TRUE())", "0.500000009486374"), "T.DIST(3E-8,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-7,0.5,TRUE())", "0.500000031818265"), "T.DIST(1E-7,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-6,0.5,TRUE())", "0.500000318324035"), "T.DIST(1E-6,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-4,0.5,TRUE())", "0.500031830988398"), "T.DIST(1E-4,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.01,0.5,TRUE())", "0.503182992764909"), "T.DIST(0.01,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.5,0.5,TRUE())", "0.647583617650433"), "T.DIST(0.5,0.5,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-9,1,TRUE())", "0.5"), "T.DIST(1E-9,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-8,1,TRUE())", "0.5"), "T.DIST(1E-8,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(3E-8,1,TRUE())", "0.500000009486374"), "T.DIST(3E-8,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-7,1,TRUE())", "0.500000031818265"), "T.DIST(1E-7,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-6,1,TRUE())", "0.500000318324035"), "T.DIST(1E-6,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-4,1,TRUE())", "0.500031830988398"), "T.DIST(1E-4,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.01,1,TRUE())", "0.503182992764909"), "T.DIST(0.01,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.5,1,TRUE())", "0.647583617650433"), "T.DIST(0.5,1,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-9,3,TRUE())", "0.5"), "T.DIST(1E-9,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-8,3,TRUE())", "0.5"), "T.DIST(1E-8,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(3E-8,3,TRUE())", "0.500000011026578"), "T.DIST(3E-8,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-7,3,TRUE())", "0.50000003675526"), "T.DIST(1E-7,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-6,3,TRUE())", "0.500000367552597"), "T.DIST(1E-6,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-4,3,TRUE())", "0.500036755259613"), "T.DIST(1E-4,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.01,3,TRUE())", "0.503675444293574"), "T.DIST(0.01,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.5,3,TRUE())", "0.674276017575924"), "T.DIST(0.5,3,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-9,10,TRUE())", "0.5"), "T.DIST(1E-9,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-8,10,TRUE())", "0.5"), "T.DIST(1E-8,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(3E-8,10,TRUE())", "0.500000011673251"), "T.DIST(3E-8,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-7,10,TRUE())", "0.500000038910838"), "T.DIST(1E-7,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-6,10,TRUE())", "0.500000389108384"), "T.DIST(1E-6,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-4,10,TRUE())", "0.500038910838325"), "T.DIST(1E-4,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.01,10,TRUE())", "0.503891012504514"), "T.DIST(0.01,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.5,10,TRUE())", "0.686053197128514"), "T.DIST(0.5,10,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-9,100,TRUE())", "0.5"), "T.DIST(1E-9,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-8,100,TRUE())", "0.5"), "T.DIST(1E-8,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(3E-8,100,TRUE())", "0.5"), "T.DIST(3E-8,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-7,100,TRUE())", "0.500000039794619"), "T.DIST(1E-7,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-6,100,TRUE())", "0.500000397946187"), "T.DIST(1E-6,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(1E-4,100,TRUE())", "0.500039794618627"), "T.DIST(1E-4,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.01,100,TRUE())", "0.503979394882786"), "T.DIST(0.01,100,TRUE())")
        self.assertTrue(_same_15("T.DIST(0.5,100,TRUE())", "0.690913217084557"), "T.DIST(0.5,100,TRUE())")
        self.assertTrue(_same_15("T.DIST.RT(1E-8,3)", "0.5"), "T.DIST.RT(1E-8,3)")
        self.assertTrue(_same_15("T.DIST.2T(1E-8,3)", "1"), "T.DIST.2T(1E-8,3)")
        self.assertTrue(_same_15("T.DIST(-1E-8,3,TRUE())", "0.5"), "T.DIST(-1E-8,3,TRUE())")
        self.assertTrue(_same_15("T.DIST.RT(1E-6,3)", "0.499999632447403"), "T.DIST.RT(1E-6,3)")
        self.assertTrue(_same_15("T.DIST.2T(1E-6,3)", "0.999999264894806"), "T.DIST.2T(1E-6,3)")
        self.assertTrue(_same_15("T.DIST(-1E-6,3,TRUE())", "0.499999632447403"), "T.DIST(-1E-6,3,TRUE())")
        self.assertTrue(_same_15("T.DIST.RT(0.01,3)", "0.496324555706426"), "T.DIST.RT(0.01,3)")
        self.assertTrue(_same_15("T.DIST.2T(0.01,3)", "0.992649111412852"), "T.DIST.2T(0.01,3)")
        self.assertTrue(_same_15("T.DIST(-0.01,3,TRUE())", "0.496324555706426"), "T.DIST(-0.01,3,TRUE())")


if __name__ == "__main__":
    unittest.main()
