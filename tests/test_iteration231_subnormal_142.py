"""Iteration 231: Task 142 dax-subnormal-142.

A subnormal double (0 < |x| < 2.2250738585072014E-308) from a literal, a text or arithmetic. Each family below follows the measured Power BI
rule (x is the double of the argument; ERR-arg and ERR-div0 are the errors the local engine reports as LOCAL-REJECT). A case the
local engine refuses where Power BI answers is a refusal, not a pass; a wrong answer fails the test. Unlisted functions and argument
positions must stay refused.

The comparison is strict for subnormal answers: the sign must match and the magnitude to 1e-9 relative. A zero answer must be an
unsigned zero (never -0).
"""
import unittest
from decimal import Decimal

from tools import dax_oracle_diff as dax

ERR_ARG = "ERR-arg"
ERR_DIV0 = "ERR-div0"
REFUSED = "REFUSED"  # outside the table: the local engine must refuse it


def _matches(expected: str, local: str) -> bool:
    if expected == REFUSED:
        return local.startswith("LOCAL-REJECT") or local.startswith("LOCAL-CRASH")
    if expected == ERR_ARG:  # the argument error (FIXED of more than 127 decimals says "has an invalid value")
        return local.startswith("LOCAL-REJECT") and "has the wrong data type" in local
    if expected == ERR_DIV0:
        return local.startswith("LOCAL-REJECT") and "Division by zero" in local
    if local.startswith("LOCAL-"):
        return False
    if local == expected:
        return True
    if expected in {"BLANK", "True", "False", "Infinity", "-Infinity"}:
        return local == expected
    try:
        want, got = Decimal(expected), Decimal(local)
    except Exception:
        return False
    if not got.is_finite() or not want.is_finite():
        return False
    if want == 0:
        return got == 0 and not got.is_signed()  # a zero is never negative (FIXED gives 0.00, SIGN gives 0)
    return got.is_signed() == want.is_signed() and abs(got - want) <= Decimal("1e-9") * abs(want)


class SubnormalFamilies142Test(unittest.TestCase):
    """Each family of the table is one test: the expression, then the Power BI answer (or the error or refusal)."""

    def _check(self, cases) -> None:
        for expression, expected in cases:
            with self.subTest(expression=expression):
                local = dax.local(expression)
                self.assertTrue(_matches(expected, local), f"{expression}: Power BI {expected}, local {local}")

    def test_sign_preserving_family(self):
        # ABS (|x|), TRUNC, ROUNDUP, ROUNDDOWN, CONVERT DOUBLE, VALUE, SIN, x+0, x/1, x*1E300, x+x keep the sign
        self._check((
            ("ABS(1E-310)", "1E-310"), ("ABS(-1E-310)", "1E-310"), ('ABS("-2e-310")', "2E-310"),
            ("TRUNC(-1E-310,2)", "-1E-310"), ("ROUNDUP(-1E-310,0)", "-1E-310"), ("ROUNDDOWN(1E-310,-1)", "1E-310"),
            ("CONVERT(-1E-310,DOUBLE)", "-1E-310"), ('VALUE("-9e-316")', "-9E-316"), ("SIN(-1E-310)", "-1E-310"),
            ("-1E-310+0", "-1E-310"), ("-1E-310/1", "-1E-310"), ("1E-310*1E300", "1E-10"),
            ("1E-310+1E-310", "2E-310"), ('"-2e-310"+0', "-2E-310"),
        ))

    def test_round_family(self):
        # ROUND(x,n) is x for a positive x and 0 for a negative one, at any n
        self._check((
            ("ROUND(1E-310,0)", "1E-310"), ("ROUND(-1E-310,0)", "0"), ("ROUND(1E-310,-1)", "1E-310"),
            ("ROUND(1E-310,320)", "1E-310"), ("ROUND(-1E-310,400)", "0"), ("ROUND(1E-310,5)", "1E-310"),
            ("ROUND(5E-320,0.5)", "4.99994433591342E-320"), ('ROUND("3e-320"*2,2)', "5.9999332030961E-320"),
            ('ROUND("-7e-315",5)', "0"),
        ))

    def test_sign_and_zero_family(self):
        # SIGN is 0 / -1; INT, CURRENCY, CONVERT INTEGER, QUOTIENT(x,d), ISO.CEILING, CEILING and FLOOR with a positive step are 0
        self._check((
            ("SIGN(1E-310)", "0"), ("SIGN(-1E-310)", "-1"), ('SIGN(-"-7e-315")', "0"),
            ("SIGN(CURRENCY(-4.4E-311))", "0"), ("SIGN(CONVERT(-4.4E-311,INTEGER))", "0"),
            ('SIGN(DIVIDE(-0.25,("6e-309"+0)))', "-1"),
            ("INT(-1E-310)", "0"), ("INT(1E-310)", "0"), ("QUOTIENT(-1E-310,3)", "0"), ("CURRENCY(-1E-310)", "0"),
            ("CONVERT(-1E-310,INTEGER)", "0"), ("ISO.CEILING(-1E-310)", "0"), ("ISO.CEILING(1E-310,0.5)", "0"),
            ("CEILING(-1E-310,1)", "0"), ("FLOOR(1E-310,0.5)", "0"), ("CEILING(1E-310,0)", "0"),
            ("LCM(1E-310,0)", "0"), ("GCD(-1E-310,0)", "0"), ("MROUND(1E-310,0)", "0"),
            ("CONVERT(1E-310,CURRENCY)", "0"), ("INT(-1E-310*1E308)", "-1"),
        ))

    def test_fixed_family(self):
        # FIXED gives 0 with the decimals, never -0; more than 127 decimals is the FIXED error
        self._check((
            ("FIXED(-1E-310,2)", "0.00"), ("FIXED(1E-310,0)", "0"), ('FIXED(VALUE("-9e-316"),10)', "0.0000000000"),
            ("FIXED(1E-310,400)", ERR_ARG),
        ))

    def test_ceiling_floor_negative_step_family(self):
        # CEILING(x,-1) and FLOOR(x,-1): ERR-arg for a positive x, 0 for a negative one; FLOOR(x,0) is the division error
        self._check((
            ("CEILING(1E-310,-1)", ERR_ARG), ("CEILING(-1E-310,-1)", "0"), ("FLOOR(1E-310,-1)", ERR_ARG),
            ("FLOOR(-1E-310,-1)", "0"), ("FLOOR(1E-310,0)", ERR_DIV0), ("FLOOR(-1E-310,0)", ERR_DIV0),
        ))

    def test_mround_family(self):
        # MROUND(x,m): m>0 gives 0 for a positive x and the error for a negative one; m<0 the mirror; m=0 gives 0
        self._check((
            ("MROUND(1E-310,1)", "0"), ("MROUND(-1E-310,1)", ERR_ARG), ("MROUND(1E-310,-1)", ERR_ARG),
            ("MROUND(-1E-310,-1)", "0"), ("MROUND(-1E-310,0)", "0"), ('MROUND("3e-320",0.5)', "0"),
        ))

    def test_mod_family(self):
        # MOD(x,d): d>0 gives the error for a positive x and 0 for a negative one; d<0 the mirror image
        self._check((
            ("MOD(1E-310,1)", ERR_ARG), ("MOD(-1E-310,1)", "0"), ("MOD(1E-310,-1)", "0"), ("MOD(-1E-310,-1)", ERR_ARG),
            ("MOD(0,1E-310)", ERR_DIV0), ("MOD(0,-1E-310)", "0"), ("MOD(5,1E-310)", ERR_DIV0), ("MOD(5,-1E-310)", ERR_ARG),
        ))

    def test_quotient_of_a_number_by_x_family(self):
        self._check((("QUOTIENT(5,1E-310)", ERR_ARG), ("QUOTIENT(5,-1E-310)", ERR_ARG), ("QUOTIENT(0,-1E-310)", ERR_ARG)))

    def test_power_family(self):
        # POWER(x,k) with k a whole number above 0 or 1 is 0; k=0 is the error for a positive x and 1 for a negative one;
        # k=-1 is the division error; k=0.5 is the square root; POWER(0,x) and POWER(2,x) and POWER(-2,x)
        self._check((
            ("POWER(1E-310,0)", ERR_ARG), ("POWER(-1E-310,0)", "1"), ("POWER(1E-310,-1)", ERR_DIV0),
            ("POWER(-1E-310,-1)", ERR_DIV0), ("POWER(1E-310,0.5)", "9.99999999999999E-156"),
            ("POWER(-1E-310,0.5)", ERR_ARG), ("POWER(1E-310,1)", "0"), ("POWER(-1E-310,1)", "0"), ("POWER(-1E-310,2)", "0"),
            ("POWER(1E-310,3)", "0"), ("POWER(0,1E-310)", "0"), ("POWER(0,-1E-310)", ERR_DIV0),
            ("POWER(2,-1E-310)", "1"), ("POWER(-2,1E-310)", ERR_ARG),
            ("SQRT(1E-310)", "9.99999999999999E-156"), ("SQRT(-1E-310)", ERR_ARG),
        ))

    def test_caret_operator_family(self):
        # the ^ operator is POWER's rules
        self._check((
            ("1E-310^0", ERR_ARG), ("1E-310^1", "0"), ("1E-310^2", "0"), ("1E-310^-1", ERR_DIV0),
            ("1E-310^0.5", "9.99999999999999E-156"), ('"-2e-310"^0', "1"), ('"-2e-310"^2', "0"), ('"1e-310"^0', ERR_ARG),
            ('"3e-320"/"3e-320"', "1"), ('"-2e-310"/1', "-1.99999999999999E-310"),
        ))

    def test_logarithm_family(self):
        self._check((
            ("LN(1E-310)", "-713.801378828154"), ("LN(-1E-310)", ERR_ARG), ("LOG10(1E-310)", "-310"),
            ("LOG10(-1E-310)", ERR_ARG), ("LOG(1E-310,10)", "-310"), ("LOG(-1E-310,10)", ERR_ARG),
        ))

    def test_factorial_and_parity_family(self):
        self._check((
            ("FACT(1E-310)", "1"), ("FACT(-1E-310)", ERR_ARG),
            ("EVEN(1E-310)", "2"), ("EVEN(-1E-310)", "-2"), ("ODD(1E-310)", "1"), ("ODD(-1E-310)", "-1"),
            ("ISEVEN(-1E-310)", "True"), ("ISODD(1E-310)", "False"), ("ISODD(-1E-310)", "False"),
        ))

    def test_logical_family(self):
        # NOT, IF (the true branch) and CONVERT to BOOLEAN read both signs alike
        self._check((
            ("NOT(1E-310)", "False"), ("NOT(-1E-310)", "False"), ('IF(-1E-310,"a","b")', "a"),
            ('IF(1E-310,1,2)', "1"), ("CONVERT(-1E-310,BOOLEAN)", "True"),
        ))

    def test_exp_cos_family(self):
        self._check((("EXP(1E-310)", "1"), ("EXP(-1E-310)", "1"), ("COS(-1E-310)", "1"), ("2^-1E-310", "1")))

    def test_degrees_radians_family(self):
        self._check((("DEGREES(3E-311*1)", "0"), ("RADIANS(5E-320)", "0"), ("DEGREES(-1E-310)", "0"), ("RADIANS(1E-310)", "0")))

    def test_divide_family(self):
        # DIVIDE(a,b) with a subnormal b is a*(1/b), and BLANK when 1/b is beyond the Double range
        self._check((
            ("DIVIDE(1E-310,1E-310)", "BLANK"), ("DIVIDE(1,1E-310)", "BLANK"), ("DIVIDE(0,-1E-310)", "BLANK"),
            ("DIVIDE(1E-310,0)", "BLANK"), ("DIVIDE(-0.25,\"6e-309\")", "-4.16666666666667E+307"),
            ("DIVIDE(1E-310,2)", "5E-311"), ("DIVIDE(-1E-310,2)", "-5E-311"),
        ))

    def test_operator_division_family(self):
        self._check((
            ("1/1E-310", "Infinity"), ("-1/1E-310", "-Infinity"), ("1E-310/1E-310", "1"), ("-1E-310/-1E-310", "1"),
            ("1E-310*0", "0"), ("-1E-310*0", "0"), ("1E-310-1E-310", "0"), ("1E-310*1E300", "1E-10"),
        ))

    def test_comparison_family(self):
        self._check((
            ("1E-310>0", "True"), ("1E-310=0", "False"), ("-1E-310<0", "True"), ("-1E-310>0", "False"),
            ("1E-310<0", "False"), ("-1E-310=0", "False"),
        ))

    def test_format_family(self):
        self.assertEqual(dax.local('FORMAT(1E-310,"0.00E+00")'), "1.00E-310")
        self.assertEqual(dax.local('FORMAT(-1E-310,"0.00E+00")'), "-1.00E-310")

    def test_unlisted_functions_and_positions_stay_refused(self):
        # refusals the engine gives today and keeps (the positions and functions the table does not list)
        self._check((
            ("MROUND(5,1E-310)", REFUSED), ("CEILING(5,1E-310)", REFUSED), ('ISO.CEILING(5,"1e-310")', REFUSED),
        ))

    def test_the_wrong_answers_on_main(self):
        # the cases that were wrong before this task: Power BI answer first
        self._check((
            ("1E-310^0", ERR_ARG), ("POWER(1E-310,0)", ERR_ARG), ("DEGREES(3E-311*1)", "0"), ("RADIANS(5E-320)", "0"),
            ("FIXED(1E-310,400)", ERR_ARG), ('FIXED(VALUE("-9e-316"),10)', "0.0000000000"),
            ("SIGN(CURRENCY(-4.4E-311))", "0"), ("SIGN(CONVERT(-4.4E-311,INTEGER))", "0"),
            ('SIGN(DIVIDE(-0.25,("6e-309"+0)))', "-1"), ("ROUND(5E-320,0.5)", "4.99994433591342E-320"),
        ))


class SubnormalReview142Test(unittest.TestCase):
    """Review fixes (Opus probes and the saved Power BI grids): the regime of SIGN, INT, ROUND and POWER near 5E-309, DEGREES, GCD, zero divisors."""

    _check = SubnormalFamilies142Test._check

    def test_sign_int_round_read_an_ordinary_number_from_5e_309(self):
        self._check((
            ('SIGN(ABS(("6e-309"+0)))', "1"), ('SIGN(SIN(("6e-309"+0)))', "1"), ('SIGN(INT("-5e-309"))', "-1"), ('INT("-5e-309")', "-1"),
            ('INT("-5e-309"+"-5e-309")', "-1"), ('INT("-5e-309"/10)', "0"), ('INT(("6e-309"+0))', "0"), ('ROUND(ABS(("6e-309"+0)),2)', "0"),
            ('SIGN(("6e-309"+0)*1E300)', "1"), ('SIGN("-2e-310")', "-1"), ('SIGN("2e-310")', "0"), ('INT("-7e-315")', "0"),
        ))

    def test_between_the_measured_zones_stays_refused(self):
        self._check((("SIGN(1E-309)", REFUSED), ("INT(-1E-309)", REFUSED), ("ROUND(1E-309,2)", REFUSED)))

    def test_degrees_and_radians_are_computed(self):
        self._check((('IFERROR(DEGREES("-5e-309"),"err")', "-2.86478897565412E-307"), ('SIGN(DEGREES("-5e-309"))', "-1"),
                     ('RADIANS(("6e-309"+0))', "0"), ("DEGREES(-1E-310)", "0")))

    def test_power_with_a_computed_subnormal_and_unlisted_exponents(self):
        self._check((
            ("POWER((1E-160*1E-155),0)", ERR_ARG), ("INT(POWER((1E-160*1E-155),0))", ERR_ARG), ("POWER((0-1E-160*1E-155),0)", "1"),
            ('"8e-312"^-0.25', ERR_DIV0), ("IFERROR((0-2E-313)^-0.25,1)", "1"), ('POWER(("6e-309"+0),-0.25)*1E-70', "1.1362193664675E+7"),
            ("POWER(10,-4.4E-311)", "1"), ("POWER(0.5,5E-320)", "1"), ("POWER(3,(3E-311*1))", "1"), ("POWER(-0.25,5E-320)", ERR_ARG),
            ('POWER(2,("6e-309"+0))', "1"), ('POWER(-5E-309,1)', "0"),
        ))

    def test_gcd_quotient_and_mod_with_a_subnormal(self):
        self._check((
            ('GCD("5e-311",1)', "1"), ('GCD(-4.4E-311,3)', "3"), ('GCD("-5e-309",-1)', ERR_ARG), ('GCD((-1E-160*1E-158),0.5)', "1"),
            ("QUOTIENT((0-2E-313),0)", ERR_DIV0), ("MOD((3E-311*1),0)", ERR_DIV0), ("SIGN(QUOTIENT(5E-320,-1))", "0"),
            ('IFERROR((-1E-160*1E-158)/0,"err")', "err"),
        ))

    def test_log_with_a_negative_base_is_the_argument_error(self):
        self._check((('LOG("8e-312",-1)', ERR_ARG),))


if __name__ == "__main__":
    unittest.main()
