"""Task 165 (dax-hunt-165): fresh Power BI hunt, batch 22. Assertions copied from the measured Power BI answers (2026-11-15).

Families done here: A (a date operand of * or / gives a Double; PV and FV with nper 0.5 take the plain square root, other fractional nper stay a known limit),
C (ACOSH is LN(x+SQRT(x*x-1)) in doubles), D (BETA.INV at the upper bound is the bound).
Not done: B (CONVERT(-1E15,DATETIME) inside IFERROR is a query error, but the locked Task 145 answer for the plain CONVERT is 01/01/0100, and
CONVERT(-1E200,DATETIME) is locked as 01/01/0100 too: the two cannot both be met by a general rule without more probes), E (last-digit statistics).
"""

import unittest
from decimal import Context, Decimal

from tools.dax_oracle_diff import local

_FIFTEEN = Context(prec=15)


def same15(text: str, expected: str) -> bool:
    """Equal at 15 significant digits, with the same sign (the hunt's rule for numbers)."""
    if text.startswith("LOCAL-"):
        return False
    return _FIFTEEN.plus(Decimal(text)) == _FIFTEEN.plus(Decimal(expected)) and Decimal(text).is_signed() == Decimal(expected).is_signed()


class TestIteration253Hunt165(unittest.TestCase):
    # Family A: * and / with a date operand are Doubles (no 28-digit Decimal quotient)
    def test_family_a_average_over_date_is_double(self):
        self.assertTrue(same15(local('IFERROR(AVERAGE(Facts[Quantity])/(DATE(2020,2,29)),"E")'), "5.69605832763727E-05"))

    def test_family_a_date_times_and_over_numbers_are_doubles(self):
        self.assertTrue(same15(local("DATE(2020,1,1)/3"), "14610.3333333333"))
        self.assertTrue(same15(local("DATE(2020,1,1)*(1/3)"), "14610.3333333333"))
        self.assertTrue(same15(local("DATE(2020,1,1)*(TIME(1,0,0))"), "1826.29166666667"))

    def test_family_a_date_plus_stays_a_date(self):
        self.assertEqual(local("DATE(2020,1,1)+0.1"), "01/01/2020 02:24:00")

    # Family A: PV and FV with nper 0.5 use the square root of 1 + rate (other fractional nper: see the t179 known limits)
    def test_family_a_pv_fractional_nper(self):
        self.assertTrue(same15(local("PV(1,0.5,1)"), "-0.292893218813453"))
        self.assertTrue(same15(local("PV(-0.5,2.5,-1000)"), "9313.70849898476"))

    def test_family_a_fv_fractional_nper(self):
        self.assertTrue(same15(local("FV(-0.5,2.5,-1000)"), "1646.44660940673"))
        self.assertTrue(same15(local("FV(1,0.5,1)"), "-0.414213562373095"))

    def test_family_a_pv_whole_nper_unchanged(self):
        self.assertTrue(same15(local("PV(1E-8,360,-1000)"), "359999.346407639"))

    # Family C: ACOSH in doubles, LN(x+SQRT(x*x-1))
    def test_family_c_acosh_of_coth(self):
        self.assertTrue(same15(local("POWER(ACOSH(COTH(7)),1)"), "0.00182376443662588"))

    def test_family_c_acosh_values(self):
        self.assertEqual(local("ACOSH(1)"), "0")
        self.assertTrue(same15(local("ACOSH(2.5)"), "1.56679923697241"))
        self.assertTrue(same15(local("ACOSH(10)"), "2.99322284612638"))

    def test_family_c_acosh_refusals_stay(self):
        self.assertTrue(local("ACOSH(0.5)").startswith("LOCAL-"))
        self.assertEqual(local("ISERROR(ACOSH(1.35E154))"), "True")
        self.assertEqual(local("ISERROR(ACOSH(1.3E154))"), "False")

    # Family D: BETA.INV at the upper bound of the solver is the bound
    def test_family_d_beta_inv_upper_bound(self):
        self.assertTrue(same15(local("BETA.INV(0.25,0.1,1E-5)"), "1"))
        self.assertEqual(local("BETA.INV(1-1E-10,0.1,0.1)"), "1")

    def test_family_d_beta_inv_alpha_one_at_bound_refuses(self):
        self.assertTrue(local("BETA.INV(0.9,1,1E-3)").startswith("LOCAL-"))


def _numeric_same(text, expected):
    """The hunt's number rule: a shortest float text stands for its exact double, then both are rounded to 15 significant digits."""
    try:
        if text.startswith("LOCAL-"):
            return False
        value = Decimal(text)
        if repr(float(text)) == text:
            value = Decimal(float(text))
        return _FIFTEEN.plus(value) == _FIFTEEN.plus(Decimal(expected)) and value.is_signed() == Decimal(expected).is_signed()
    except Exception:
        return False


class TestIteration253Hunt165Batch22(unittest.TestCase):
    """Task 165 follow-up: every row of the coordinator's 39-row edge set (t178), measured in Power BI on 2026-11-15."""

    def _check(self, expr, pbi):
        loc = local(expr)
        if pbi.startswith("ERR"):
            self.assertTrue(loc.startswith("LOCAL-"), loc)
            return
        if loc != pbi and not _numeric_same(loc, pbi):
            self.fail(f"{expr}: local {loc!r} != Power BI {pbi!r}")

    def test_t178_00(self):
        self._check("DATE(2020,2,29)*2", "87780")

    def test_t178_01(self):
        self._check("DATE(2020,2,29)*1.5", "65835")

    def test_t178_02(self):
        self._check("DATE(2020,2,29)/3", "14630")

    def test_t178_03(self):
        self._check("DATE(2020,2,29)/7&\"z\"", "6270z")

    def test_t178_04(self):
        self._check("3/DATE(2020,2,29)", "6.83526999316473E-05")

    def test_t178_05(self):
        self._check("DATE(2020,1,1)*SUM(Facts[Sales])", "1380676.5")

    def test_t178_06(self):
        self._check("(DATE(2020,1,1)*0.1)&\"z\"", "4383.1z")

    def test_t178_07(self):
        self._check("DATE(2020,2,29)*CURRENCY(1.5)", "65835")

    def test_t178_08(self):
        self._check("DATE(2020,2,29)/CURRENCY(3)", "14630")

    def test_t178_09(self):
        self._check("DATEVALUE(\"2020-01-01\")/3", "14610.3333333333")

    def test_t178_10(self):
        self._check("DATE(2020,2,29)*2&\"\"", "87780")

    def test_t178_11(self):
        self._check("AVERAGE(Facts[Sales])/DATE(2020,1,1)", "0.000143733886974972")

    def test_t178_12(self):
        self._check("DATE(2020,1,1)/DATE(2019,1,1)", "1.00839736805779")

    def test_t178_13(self):
        self._check("INT(DATE(2020,1,1)/7)", "6261")

    def test_t178_14(self):
        self._check("ACOSH(1.0000001)", "0.000447213591894773")

    def test_t178_15(self):
        self._check("ACOSH(2)", "1.31695789692482")

    def test_t178_16(self):
        self._check("ACOSH(1E10)", "23.7189981105004")

    def test_t178_17(self):
        self._check("ACOSH(1E200)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"Query (1, 19) An argument of function 'ACOSH' has the wrong data type or the result is too large or too small.\"")

    def test_t178_18(self):
        self._check("ACOSH(1.5)", "0.962423650119207")

    def test_t178_19(self):
        self._check("ACOSH(10)", "2.99322284612638")

    @unittest.expectedFailure  # known limit (coordinator): ACOSH(COTH(3))
    def test_t178_20(self):
        self._check("ACOSH(COTH(3))", "0.0996565325164423")

    def test_t178_21(self):
        self._check("ACOSH(1+1E-12)", "1.41427642308353E-06")

    def test_t178_22(self):
        self._check("ACOSH(1E154)", "355.291251501643")

    def test_t178_23(self):
        self._check("ACOSH(1)", "0")

    def test_t178_24(self):
        self._check("PV(0.05,2.5,100)", "-229.659731612638")

    def test_t178_25(self):
        self._check("PV(0.1,0.25,-50,1000,1)", "-963.503838998281")

    def test_t178_26(self):
        self._check("FV(0.05,2.5,100)", "-259.452643894091")

    def test_t178_27(self):
        self._check("FV(0.1,0.5,-10,100,1)", "-99.5119115182985")

    def test_t178_28(self):
        self._check("PV(0.05,10,100)", "-772.173492918481")

    def test_t178_29(self):
        self._check("FV(0.02,3.7,-5)", "19.0051807898262")

    def test_t178_30(self):
        self._check("PV(-0.5,0.5,1)", "-0.82842712474619")

    def test_t178_31(self):
        self._check("BETA.INV(0.999999,2,3)", "0.993690426329795")

    def test_t178_32(self):
        self._check("BETA.INV(0.5,0.1,1E-5)", "1")

    def test_t178_33(self):
        self._check("BETA.INV(0.999,0.5,0.5)", "0.999997532600929")

    def test_t178_34(self):
        self._check("BETA.INV(0.9,1,1E-3)", "ERR:Exception calling \"Read\" with \"0\" argument(s): \"Query (1, 19) An argument of function 'BETA.INV' has the wrong data type or the result is too large or too small. If the argument is expected to be a date, that date must be between March 1, 1900 and December 31, 9999.\"")

    def test_t178_35(self):
        self._check("BETA.INV(0.99999,5,1)", "0.999997999992")

    @unittest.expectedFailure  # known limit (coordinator): BETA.INV(0.1,0.1,1)
    def test_t178_36(self):
        self._check("BETA.INV(0.1,0.1,1)", "1E-10")

    @unittest.expectedFailure  # known limit (coordinator): BETA.INV(0.2,0.1,0.1)
    def test_t178_37(self):
        self._check("BETA.INV(0.2,0.1,0.1)", "9.08146855854956E-05")

    def test_t178_38(self):
        self._check("DATE(2020,1,1)*SUM(Facts[Sales])/2", "690338.25")


# Task 165 batch t179: 80 PV/FV rows measured in Power BI; the exact ones are asserted, the rest are known limits (the engine's own fractional power is not correctly rounded)
class TestIteration253Hunt165T179(unittest.TestCase):
    def _check(self, expr, pbi):
        self.assertTrue(same15(local(expr), pbi), (expr, local(expr), pbi))

    def test_t179_01(self):
        self._check("FV(-0.2,0.25,250.75)", "-68.0264577122683")

    def test_t179_02(self):
        self._check("FV(-0.2,0.5,-50)", "26.393202250021")

    def test_t179_03(self):
        self._check("FV(-0.2,4,250.75,0)", "-740.214")

    def test_t179_04(self):
        self._check("FV(-0.2,7.3,1,1000)", "-200.155136208387")

    def test_t179_05(self):
        self._check("FV(0.01,2.5,-50,0,0)", "125.93906055271")

    def test_t179_06(self):
        self._check("FV(0.01,2.5,100)", "-251.87812110542")

    def test_t179_07(self):
        self._check("FV(0.01,3.7,100)", "-375.023354504094")

    def test_t179_08(self):
        self._check("FV(0.01,3.7,100,-500,1)", "139.97757967607")

    def test_t179_09(self):
        self._check("FV(0.03,0.5,100,0)", "-49.6305216974065")

    def test_t179_10(self):
        self._check("FV(0.03,1.5,-50,1000,0)", "-969.776112530334")

    @unittest.expectedFailure  # known limit (measured): FV(0.03,1.5,250.75)
    def test_t179_11(self):
        self._check("FV(0.03,1.5,250.75)", "-378.931989150935")

    def test_t179_12(self):
        self._check("FV(0.03,4,-1000)", "4183.627")

    def test_t179_13(self):
        self._check("FV(0.05,0.5,250.75)", "-123.845809128739")

    def test_t179_14(self):
        self._check("FV(0.05,10.5,100)", "-1338.24060870492")

    def test_t179_15(self):
        self._check("FV(0.05,3.7,250.75,-500,0)", "-393.267462256129")

    def test_t179_16(self):
        self._check("FV(0.05,36.5,0,1000)", "-5934.84547907941")

    @unittest.expectedFailure  # known limit (measured): FV(0.07,7.3,0,-500)
    def test_t179_17(self):
        self._check("FV(0.07,7.3,0,-500)", "819.354006048578")

    def test_t179_18(self):
        self._check("FV(0.08/12,1.5,-1000)", "1502.49722914357")

    def test_t179_19(self):
        self._check("FV(0.08/12,12.25,-1000,1000,0)", "11635.2016324662")

    def test_t179_20(self):
        self._check("FV(0.08/12,12.25,1)", "-12.7200016434224")

    def test_t179_21(self):
        self._check("FV(0.08/12,12.25,250.75,1000,1)", "-4295.60402579157")

    def test_t179_22(self):
        self._check("FV(0.08/12,3.7,100,1000,1)", "-1400.72105161332")

    def test_t179_23(self):
        self._check("FV(0.08/12,36.5,0,1000)", "-1274.46414167889")

    def test_t179_24(self):
        self._check("FV(0.08/12,36.5,1)", "-41.1696212518342")

    def test_t179_25(self):
        self._check("FV(0.1,0.25,100)", "-24.1136890844451")

    def test_t179_26(self):
        self._check("FV(0.1,1.5,250.75)", "-385.377005465321")

    def test_t179_27(self):
        self._check("FV(0.1,12.25,100,1000)", "-5428.21492562211")

    def test_t179_28(self):
        self._check("FV(0.1,3.7,-1000)", "4228.2974278364")

    def test_t179_29(self):
        self._check("FV(0.1,7.3,-1000,-500)", "11055.0317535149")

    def test_t179_30(self):
        self._check("FV(0.12,1.5,-50)", "77.2069113987236")

    def test_t179_31(self):
        self._check("FV(0.12,10.5,1)", "-19.0576732306477")

    def test_t179_32(self):
        self._check("FV(0.12,2.5,250.75,1000,0)", "-2011.93795778412")

    def test_t179_33(self):
        self._check("FV(0.25,0.25,-1000,-500)", "758.170685482538")

    def test_t179_34(self):
        self._check("FV(0.25,0.5,100)", "-47.213595499958")

    def test_t179_35(self):
        self._check("FV(0.25,1.5,-50,-500,1)", "798.156864453026")

    def test_t179_36(self):
        self._check("FV(0.5,1.5,-10)", "16.7423461417477")

    @unittest.expectedFailure  # known limit (measured): FV(0.5,1.5,-50)
    def test_t179_37(self):
        self._check("FV(0.5,1.5,-50)", "83.7117307087384")

    def test_t179_38(self):
        self._check("FV(0.5,10.5,100,-500,0)", "21387.4882551178")

    def test_t179_39(self):
        self._check("FV(1,1.5,-1000)", "1828.42712474619")

    def test_t179_40(self):
        self._check("FV(1,2.5,-50)", "232.842712474619")

    def test_t179_41(self):
        self._check("FV(1,2.5,0,-500)", "2828.42712474619")

    def test_t179_42(self):
        self._check("FV(1,7.3,100)", "-15658.6484908149")

    def test_t179_43(self):
        self._check("PV(-0.2,3.7,1,1000,0)", "-2289.73801284603")

    def test_t179_44(self):
        self._check("PV(0.01,1.5,250.75)", "-371.477678697546")

    def test_t179_45(self):
        self._check("PV(0.01,12.25,-50)", "573.778172819786")

    def test_t179_46(self):
        self._check("PV(0.01,4,100,-500,0)", "90.2936170695708")

    @unittest.expectedFailure  # known limit (measured): PV(0.01,7.3,250.75,1000)
    def test_t179_47(self):
        self._check("PV(0.01,7.3,250.75,1000)", "-2686.7438478681")

    def test_t179_48(self):
        self._check("PV(0.03,12.25,-50)", "506.306673039124")

    def test_t179_49(self):
        self._check("PV(0.03,2.5,-1000,0,1)", "2445.65442834003")

    def test_t179_50(self):
        self._check("PV(0.03,4,-1000,-500,0)", "4161.34192676821")

    @unittest.expectedFailure  # known limit (measured): PV(0.03,7.3,-1000,1000,1)
    def test_t179_51(self):
        self._check("PV(0.03,7.3,-1000,1000,1)", "5857.73422022249")

    def test_t179_52(self):
        self._check("PV(0.03,7.3,250.75)", "-1622.24231671772")

    def test_t179_53(self):
        self._check("PV(0.05,0.25,-10)", "2.42469051538515")

    def test_t179_54(self):
        self._check("PV(0.05,7.3,1,1000)", "-706.347715508483")

    def test_t179_55(self):
        self._check("PV(0.07,0.5,1)", "-0.475193013633377")

    def test_t179_56(self):
        self._check("PV(0.07,1.5,1)", "-1.37868505947045")

    def test_t179_57(self):
        self._check("PV(0.07,10.5,-10)", "72.6514557304049")

    def test_t179_58(self):
        self._check("PV(0.07,10.5,-1000)", "7265.1455730405")

    def test_t179_59(self):
        self._check("PV(0.07,3.7,250.75,1000,1)", "-1627.37706429079")

    def test_t179_60(self):
        self._check("PV(0.07,36.5,-10)", "130.768039950147")

    @unittest.expectedFailure  # known limit (measured): PV(0.07,7.3,250.75)
    def test_t179_61(self):
        self._check("PV(0.07,7.3,250.75)", "-1396.18731735236")

    def test_t179_62(self):
        self._check("PV(0.08/12,0.5,0,-500,1)", "498.341620638822")

    def test_t179_63(self):
        self._check("PV(0.08/12,1.5,100,1000,1)", "-1139.83407084625")

    def test_t179_64(self):
        self._check("PV(0.08/12,10.5,-1000)", "10108.4337741334")

    @unittest.expectedFailure  # known limit (measured): PV(0.08/12,12.25,-50,0,0)
    def test_t179_65(self):
        self._check("PV(0.08/12,12.25,-50,0,0)", "586.28325566714")

    def test_t179_66(self):
        self._check("PV(0.08/12,3.7,-10)", "36.4275946208554")

    def test_t179_67(self):
        self._check("PV(0.12,0.5,-1000,0,0)", "459.073478974433")

    def test_t179_68(self):
        self._check("PV(0.12,0.5,1,-500,0)", "471.99651778256")

    def test_t179_69(self):
        self._check("PV(0.12,2.5,-1000,-500)", "2432.66029196107")

    def test_t179_70(self):
        self._check("PV(0.12,3.7,0,0)", "0")

    def test_t179_71(self):
        self._check("PV(0.12,7.3,-1000,1000,0)", "4252.5342672676")

    def test_t179_72(self):
        self._check("PV(0.25,0.5,250.75)", "-105.889527427084")

    def test_t179_73(self):
        self._check("PV(0.25,3.7,250.75)", "-563.72763236714")

    def test_t179_74(self):
        self._check("PV(0.25,4,1)", "-2.3616")

    def test_t179_75(self):
        self._check("PV(0.5,1.5,-10)", "9.11337892096365")

    def test_t179_76(self):
        self._check("PV(0.5,12.25,1,0,0)", "-1.98607125228657")

    def test_t179_77(self):
        self._check("PV(1,0.25,1)", "-0.159103584746285")

    def test_t179_78(self):
        self._check("PV(1,3.7,-50,1000,1)", "15.358821582537")

    def test_t179_79(self):
        self._check("PV(1,4,100)", "-93.75")

    def test_t179_80(self):
        self._check("PV(1,7.3,100)", "-99.3654278153467")


if __name__ == "__main__":
    unittest.main()
