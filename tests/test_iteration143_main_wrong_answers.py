"""Iteration 143: Task 53 -- seven shapes main answered wrongly (measured live in Power BI) are refused, and nearby locked answers stay.

- the text of a date after day zero on an exact half second (the double decides the rounding) is refused;
- a type test of arithmetic around a failing CONVERT of a text literal, with a division beside a column read or with three operands
  of which two read data, is refused (Power BI raises the conversion error);
- ISERROR of a product of a failing VALUE literal, a scan-free BLANK and a column read is refused (Power BI: False).
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

# (expression, Power BI answer) measured live
WRONG_SHAPES = [
    ('CONCATENATEX({1,2},DATE(1899,12,29)+1.5/86400+[Value],"|")', "12:00:01 AM|12/31/1899 12:00:01 AM"),
    ('CONCATENATEX({1,2},DATE(1899,12,29)+2.5/86400+[Value],"|")', "12:00:03 AM|12/31/1899 12:00:03 AM"),
    ('ISDATETIME(((CONVERT("z",INTEGER))-(SELECTEDVALUE(Facts[Quantity])))+(COUNTROWS(FILTER(Facts,FALSE()))))',
     "ERR:Cannot convert value 'z' of type Text to type Integer."),
    ('ISERROR(((VALUE("x"))*(SELECTEDVALUE(Facts[Quantity])))*(MAX(Facts[Note])))', "False"),
    ('ISINTEGER(((CONVERT("z",INTEGER))/(COUNTROWS(FILTER(Facts,FALSE()))))^(MAX(Facts[Region])))',
     "ERR:Cannot convert value 'z' of type Text to type Integer."),
    ('ISLOGICAL((CONVERT("z",INTEGER))/(MAX(Facts[Region])))', "ERR:Cannot convert value 'z' of type Text to type Integer."),
    ('ISSTRING(((CONVERT("z",INTEGER))||(MAX(Facts[Region])))/(TRUE()))', "ERR:Cannot convert value 'z' of type Text to type Integer."),
]

# answers that stay (measured and locked before this iteration)
STAYS = [
    ('ISBOOLEAN((CONVERT("z",INTEGER))+(MAX(Facts[Sales])))', "False"),
    ('ISLOGICAL((CONVERT("z",INTEGER))||(MAX(Facts[Sales])))', "True"),
    ('ISTEXT((SELECTEDVALUE(Facts[Quantity]))*(CONVERT("z",INTEGER)))', "False"),
    ('ISDATETIME(((CONVERT("z",INTEGER))-(BLANK()))^(CURRENCY(2)))', "False"),
    ('ISERROR((SELECTEDVALUE(Facts[Quantity]))*(VALUE("x")))', "False"),
    ('ISERROR(2*(SELECTEDVALUE(Facts[Note]))*(VALUE("x")))', "False"),
    ('ISERROR((VALUE("x"))*(MAX(Facts[Sales])))', "True"),
    ('ISERROR((FIRSTNONBLANK(Facts[Region],BLANK()))*(VALUE("x"))*2)', "True"),
]


class MainWrongAnswers53Tests(unittest.TestCase):
    def test_wrong_shapes_are_match_or_refused(self) -> None:
        for expression, powerbi in WRONG_SHAPES:
            ours = dax.local(expression)
            self.assertIn(status(powerbi, ours), {"match", "gap-reject"}, f"{expression} -> {ours}")

    def test_half_second_after_day_zero_is_refused(self) -> None:
        for expression in (
            'CONCATENATEX({1,2},DATE(1899,12,29)+1.5/86400+[Value],"|")',
            'CONCATENATEX({1,2},DATE(1899,12,29)+2.5/86400+[Value],"|")',
        ):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), expression)

    def test_whole_seconds_and_other_texts_still_answer(self) -> None:
        self.assertEqual("12:00:01 AM|12/31/1899 12:00:01 AM", dax.local('CONCATENATEX({1,2},DATE(1899,12,29)+1/86400+[Value],"|")'))
        self.assertEqual("12/31/1899 12:00:01 AM", dax.local("CONCATENATEX({1},DATE(1899,12,30)+1/86400+[Value],\"|\")"))

    def test_locked_neighbours_keep_their_answers(self) -> None:
        for expression, powerbi in STAYS:
            self.assertTrue(dax.same(powerbi, dax.local(expression)), f"{expression} -> {dax.local(expression)}")


if __name__ == "__main__":
    unittest.main()
