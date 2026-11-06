"""Iteration 154: Task 64 typeerr-fail-54.

A type test of a failing value is answered from the families measured on the typeerr-fail-54 grid (1,500 fresh Power BI shapes, 2026-11-06)
and the saved batteries.  A family is answered only where every measured row agrees with it:
- static: a non-numeric type test of a SWITCH / IF / COALESCE whose other branches are numbers, dates or BLANK (a SIGN branch is refused),
  and a type test of ABS( failing call + operand ) with a known static type;
- error: a text or logical branch beside a failing number (a Variant); ISNUMBER / ISNUMERIC / ISDOUBLE of a SWITCH / COALESCE with a failing
  branch beside numbers, dates or BLANK; a DATE / TIME / DATEVALUE call that fails under + or in a comparison.
- refused: a VAR ... RETURN v & "" over a failing call; ISBLANK of a comparison of a failing call with a text literal.
The Power BI answers below are recorded values of the grid (out.txt) and of tools/parity/task64_typeerr_spec.json.
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

REFUSAL = "A type test of a failing value Power BI may raise"

# static type answers (Power BI False, measured)
STATIC = (
    ('ISBOOLEAN(SWITCH(1,1,ABS("m"),1))', "False"),
    ('ISLOGICAL(SWITCH(1,1,CONVERT("z",INTEGER),2.5))', "False"),
    ('ISDATETIME(COALESCE((VAR y=TRUNC("k") RETURN y),1))', "False"),
    ('ISINT64(ABS((INT("a"))+(2.5)))', "False"),
    ('ISINT64(ABS((ROUND("c",1))+(1)))', "False"),
)

# errors Power BI raises (measured)
ERRORS = (
    ('ISCURRENCY(COALESCE((VAR y=ROUND("c",1) RETURN y),"t"))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 52) Cannot convert value \'c\' of type Text to type Number."'),
    ('ISNUMERIC(SWITCH(1,1,ABS("m"),BLANK()))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 44) Cannot convert value \'m\' of type Text to type Number."'),
    ("ISDOUBLE(SWITCH(1,1,ROUND(\"c\",1),1))", 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 45) Cannot convert value \'c\' of type Text to type Number."'),
    ('ISNUMBER(COALESCE((VAR y=ROUND("c",1) RETURN y),"t"))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 50) Cannot convert value \'c\' of type Text to type Number."'),
    ('ISTEXT((DATE("y",1,1))+(BLANK()))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 32) Cannot convert value \'y\' of type Text to type Integer."'),
)

# held-out rows (Power BI 2026-11-06): a wrapper around a failing value of the type the test asks for shows the error
ERRORS += (
    ('ISINT64(IF(1=0,BLANK(),INT("b")))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 46) Cannot convert value \'b\' of type Text to type Number."'),
    ('ISDATETIME(COALESCE((VAR y=DATE(2020,"m",1) RETURN y),BLANK()))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 56) Cannot convert value \'m\' of type Text to type Integer."'),
    ('ISCURRENCY(VAR v=CURRENCY("d") RETURN v+1)', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 45) Cannot convert value \'d\' of type Text to type Currency."'),
    ('ISDECIMAL(VAR v=CURRENCY("d") RETURN v*2)', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 44) Cannot convert value \'d\' of type Text to type Currency."'),
)

# a bare failing call of the asked type is NOT wrapped: Power BI answers True (measured)
BARE_TRUE = (
    ('ISINT64(INT("b"))', "True"),
    ('ISDOUBLE(ABS("m"))', "True"),
    ('ISINTEGER(SIGN("s"))', "True"),
)

# Part B (main answered False; Power BI raises): each must show the error or be refused
PART_B = (
    ('ISBLANK((ABS("m"))=("t"))', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 27) DAX comparison operations do not support comparing values of type Number with values of type Text. Consider using the VALUE or FORMAT function to convert one of the values."'),
    ('ISLOGICAL((DATE("y",1,1))+(1))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 35) Cannot convert value \'y\' of type Text to type Integer."'),
    ('ISLOGICAL((DATE("y",1,1))+(DATE(2020,1,1)))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 35) Cannot convert value \'y\' of type Text to type Integer."'),
    ('ISNONTEXT(VAR v=CONVERT("z",INTEGER) RETURN v&"")', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 43) Cannot convert value \'z\' of type Text to type Integer."'),
    ('ISNONTEXT(VAR v=POWER("p",2) RETURN v&"")', 'ERR:Exception calling "ExecuteReader" with "0" argument(s): "Query (1, 41) Cannot convert value \'p\' of type Text to type Integer."'),
    ('ISTEXT((DATE("y",1,1))+(BLANK()))', 'ERR:Exception calling "Read" with "0" argument(s): "Query (1, 32) Cannot convert value \'y\' of type Text to type Integer."'),
)

# still refused: a SIGN branch beside a number (the grid disagrees on the test: ISDECIMAL errors, ISINT64 is False)
STILL_REFUSED = (
    ('ISINT64(SWITCH(TRUE(),1=1,SIGN("s"),CURRENCY(1)))', "False"),
)


class TypeErrFail54Tests(unittest.TestCase):
    def test_static_families_answer_as_power_bi(self):
        for expression, powerbi in STATIC:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_error_families_show_the_failure(self):
        for expression, powerbi in ERRORS:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")

    def test_bare_failing_call_of_asked_type_is_true(self):
        for expression, powerbi in BARE_TRUE:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_part_b_rows_show_the_error_or_refuse(self):
        for expression, powerbi in PART_B:
            with self.subTest(expression=expression):
                ours = dax.local(expression)
                self.assertTrue(ours.startswith("LOCAL-REJECT"), ours)
                self.assertTrue(powerbi.startswith("ERR"))
                self.assertEqual(status(powerbi, ours), "match")

    def test_still_refused_family_stays_refused(self):
        for expression, powerbi in STILL_REFUSED:
            with self.subTest(expression=expression):
                self.assertFalse(powerbi.startswith("ERR"))
                self.assertIn(REFUSAL, dax.local(expression))


if __name__ == "__main__":
    unittest.main()
