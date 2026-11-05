"""Iteration 147: Task 57 failing-type-tests-47.

Type tests of a failing & (text) or + - * (Double) argument, answered as the measured Power BI answers in
tools/parity/task57_failing_type_tests_spec.json (the expected values below are copied from that spec), and the shapes the locked batteries
measured as errors, which stay refused: calls outside the measured set (UNICHAR, SQRT, LN, SIN, VALUE, CONVERT), SELECTEDVALUE beside the
failing part, FACT / non-literal ^ in a concatenation, and a column read beside a failing && || AND OR.
"""
import unittest

from tools import dax_oracle_diff as dax


class FailingTypeTests47Tests(unittest.TestCase):
    def assertRefused(self, expression: str) -> None:
        self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), f"{expression} -> {dax.local(expression)}")

    def test_text_concatenation_around_a_failing_part(self) -> None:
        self.assertEqual("False", dax.local('ISNONTEXT(("a"+1)&(SUM(Facts[Sales])))'))
        self.assertEqual("False", dax.local('ISNUMBER(("a"+1)&(MAX(Facts[Note])))'))
        self.assertEqual("False", dax.local('ISNONTEXT(((-1)^0.5)&("b"))'))
        self.assertEqual("True", dax.local('ISSTRING(("")&((-1)^0.5))'))
        self.assertEqual("False", dax.local('ISNUMERIC((MAX(Facts[Note]))&(NOT("a")))'))

    def test_double_around_a_failing_text(self) -> None:
        self.assertEqual("True", dax.local('ISNUMBER(("a"*2)+(COUNTROWS(FILTER(Facts,FALSE()))))'))
        self.assertEqual("True", dax.local('ISNUMBER(("a"+1)+(SUMX(FILTER(Facts,FALSE()),1)))'))
        self.assertEqual("True", dax.local('ISNUMBER((VAR y="b" RETURN y)+(2.5))'))

    def test_regressed_shapes_stay_refused(self) -> None:
        self.assertRefused('ISLOGICAL(LEFT("a",0)||MIN(Facts[Note])&"")')  # Power BI raises
        self.assertRefused('ISLOGICAL(OR(LEFT("a",0),MIN(Facts[Note])&""))')
        self.assertRefused('ISLOGICAL(2.5&&UNICHAR(32)&"")')
        self.assertRefused('ISLOGICAL(AND(1,UNICHAR(32)&""))')
        self.assertRefused('ISNUMBER((SQRT(-1))&(MAX(Facts[Sales])))')
        self.assertRefused('ISTEXT((SIN("a"))&(1))')
        self.assertRefused('ISNONTEXT((BLANK()^BLANK())&(SUM(Facts[Sales])))')
        self.assertRefused('ISNONTEXT((FACT(-1))&(MAX(Facts[Sales])))')
        self.assertRefused('ISNUMBER(("a"+1)&(SELECTEDVALUE(Facts[Quantity])))')
        self.assertRefused('ISNUMBER((1)*(VAR y="b" RETURN y))')
        self.assertRefused('ISDOUBLE(("a"*2)*(SUMX(FILTER(Facts,FALSE()),1)))')
        self.assertRefused('ISNUMBER((SUMX(FILTER(Facts,FALSE()),1))+(VAR y="b" RETURN y))')

    def test_failing_datevalue_beside_another_failing_operand_is_refused(self) -> None:
        # Power BI (measured live) raises "Cannot convert ..." for each of these
        self.assertRefused('ISDOUBLE(("b"-3)*(DATEVALUE("zz")))')
        self.assertRefused('ISTEXT((INT("a"))&&(DATEVALUE("zz")))')
        self.assertRefused('ISINT64(("b"-3)||(DATEVALUE("zz")))')


if __name__ == "__main__":
    unittest.main()
