"""Iteration 140: Task 50 type-tests-errors-40.

Type tests and BLANK tests of a failing value, answered the way Power BI answers them, only for the measured families (every other failing
shape keeps raising or being refused, because the locked batteries show Power BI raising for it):
- a type test of + - * arithmetic, & text, CONCATENATE / UPPER text and && || AND OR logic whose calls are all in a small measured set and
  that has no division (the answer is the static type's; ISCURRENCY / ISDATETIME / ISINT64 only without FACT, MOD, ^ and DATE);
- VAR q = (a failing value) * (a factor that evaluates to BLANK) RETURN ISBLANK(q);
- ISBLANK of a Currency division under a never-blank operator is not raised.
"""
import unittest

from tools import dax_oracle_diff as dax


class TypeTestsErrors40Tests(unittest.TestCase):
    def assertRefused(self, expression: str) -> None:
        self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), f"{expression} -> {dax.local(expression)}")

    def test_type_of_failing_arithmetic_is_its_static_type(self) -> None:
        self.assertEqual("False", dax.local("ISLOGICAL((FACT(-1))*(2.5))"))
        self.assertEqual("False", dax.local("ISTEXT((MOD(1,0))*(\"\"))"))
        self.assertEqual("True", dax.local("ISNONTEXT((MOD(1,0))*(\"\"))"))
        self.assertEqual("False", dax.local('ISCURRENCY(("a")*("2"))'))
        self.assertEqual("True", dax.local('ISDATETIME(DATE(2020,1,1)-"Jan")'))  # a date in the arithmetic is not answered as a Double
        self.assertRefused("ISNUMBER((2.5)+((-1)^0.5))")  # measured both ways, not modelled
        self.assertRefused("ISCURRENCY(2.5*(LN(-1)))")  # LN is evaluated at once by Power BI (raises)
        self.assertRefused('ISINT64((-1)/("a"))')  # a division raises in Power BI

    def test_type_of_failing_text_and_logical(self) -> None:
        self.assertEqual("True", dax.local('ISTEXT((MOD(1,0))&("b"))'))
        self.assertEqual("False", dax.local('ISNUMBER((MOD(1,0))&("b"))'))
        self.assertEqual("True", dax.local('ISTEXT(CONCATENATE(EXP("w"),"t"))'))
        self.assertRefused('ISNONTEXT(NOT("a"))')  # fewer than five measured rows
        self.assertRefused('ISTEXT((CONVERT("z",INTEGER))&(BLANK()))')  # Power BI raises
        self.assertRefused('ISLOGICAL(MAX(Facts[Note])&""&&1)')  # a column read beside the failing part: Power BI raises, so only literal operands are answered
        self.assertRefused('ISTEXT((NOT("a"))-(SELECTEDVALUE(Facts[Quantity])))')
        self.assertRefused("ISSTRING(UPPER(FACT(-1)))")  # CONCATENATE / UPPER of FACT or MOD raise in Power BI
        self.assertEqual("True", dax.local('ISNONTEXT(TRUE()&&(1/0))'))

    def test_failing_product_with_a_blank_is_blank(self) -> None:
        self.assertEqual("True", dax.local("VAR q=(COUNTROWS(FILTER(Facts,FALSE())))*(FACT(-1)) RETURN ISBLANK(q)"))
        self.assertEqual("True", dax.local('VAR q=(ERROR("x"))*(COUNTROWS(FILTER(Facts,FALSE()))) RETURN ISBLANK(q)'))
        self.assertRefused("VAR q=(COUNTROWS(FILTER(Facts,FALSE())))*(LOG10(0))+(SUM(Facts[Sales])) RETURN ISBLANK(q)")  # a + over a failing product: not modelled yet
        self.assertRefused('VAR q=(SUMX(Facts,ERROR("x")))*(CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope")) RETURN ISBLANK(q)')  # an iterator raises first
        self.assertRefused('ISBLANK((LOOKUPVALUE(Facts[Quantity],Facts[Region],"Nope"))/(ERROR("x")))')  # written inline it raises

    def test_literal_operand_keeps_the_failing_value_non_blank(self) -> None:
        self.assertEqual("False", dax.local("ISBLANK(2*(MOD(1,0)))"))
        self.assertEqual("False", dax.local("ISBLANK(MOD(1,0)*2)"))
        self.assertEqual("False", dax.local("ISBLANK(1/0+1)"))

    def test_currency_division_under_never_blank_operator_is_not_raised(self) -> None:
        self.assertEqual("False", dax.local('ISBLANK(((CURRENCY(MAX(Facts[Quantity])))/(0))&"z")'))
        self.assertEqual("False", dax.local("ISBLANK(2/((CURRENCY(MAX(Facts[Quantity])))/(0)))"))
        self.assertEqual("False", dax.local("ISBLANK(((CURRENCY(MAX(Facts[Quantity])))/(0.0))+1)"))

    def test_unmeasured_shapes_stay_refused(self) -> None:
        self.assertRefused("ISDOUBLE((FACT(-1))*(2.5))")
        self.assertRefused("ISNUMERIC((FACT(-1))*(2.5))")
        self.assertRefused('ISBLANK(VARX.S({"a"},CONVERT(2.5,INTEGER)))')


if __name__ == "__main__":
    unittest.main()
