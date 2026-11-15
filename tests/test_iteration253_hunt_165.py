"""Task 165 (dax-hunt-165): fresh Power BI hunt, batch 22. Assertions copied from the measured Power BI answers (2026-11-15).

Families done here: A (a date operand of * or / gives a Double; PV and FV with a fractional nper use the correctly rounded power),
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

    # Family A: PV and FV with a fractional nper use the correctly rounded double power
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


if __name__ == "__main__":
    unittest.main()
