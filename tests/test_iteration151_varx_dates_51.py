"""Iteration 151: Task 61 varx-dates-51.

VARX.P / VARX.S / STDEVX over a date body with a division is answered in Power BI's double arithmetic: each row's value is
computed in doubles, left to right, then spread by dax_math.double_statistic.  The Power BI answers below are recorded values of
tools/parity/task61_varx_dates_spec.json.  A body the double evaluator does not model (here an IF inside the body) keeps the refusal.
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

REFUSAL = "over a date in a conditional is not exact in the local engine"

# (expression, Power BI answer) pairs measured on the Windows VM for Task 61
ANSWERED = (
    ("VARX.P({1,2,3},DATE(2020,1,1)+[Value]/3)", "0.0740740299224854"),
    ("CALCULATE(VARX.P({1,2,3},DATE(2020,1,1)+[Value]/3),Facts[Region]=\"West\")", "0.0740740299224854"),
    ("VARX.P({5,9},DATE(1900,3,1)+[Value]/3)", "0.444444444445253"),
    ("(VARX.P({5,9},DATE(1899,12,31)+[Value]/3))&\"z\"", "0.444444444444445z"),
    ("VARX.P({5,9},DATE(2000,1,1)+[Value]/3)", "0.44444465637207"),
    ("VARX.P(Facts,DATE(2000,1,1)+Facts[Quantity]/3)", "0.324073791503906"),
)

# fresh Power BI grid (Task 61 fix): a quotient of a date, a date over a divisor, a list body, an all-equal body that is exact in doubles
FRESH = (
    ("STDEVX.P(Facts,(DATE(2031,4,17)+Facts[Quantity])/0.3)", "5.69275062408049"),
    ("VARX.P({4,9,2,5,10},(DATE(2020,5,5)+[Value])/1.5)", "4.0888888835907"),
    ("STDEVX.P({10,4,2},(DATE(2000,7,1)+[Value])/7)", "0.485620911309742"),
    ("STDEVX.P({3,3,2,0.5,5},DATE(2000,10,25)/2+[Value])", "1.46969383431428"),
    ("VARX.P(Facts,(DATE(1900,2,28)+Facts[Sales])/11)&\"z\"", "0.486742424242436z"),
    ("VARX.P({3,4,0.5},(DATE(1900,2,28)+[Value])/1.5)&\"z\"", "0.962962962963275z"),
    ("STDEVX.P(ALL(Facts),DATE(1900,3,1)+1/4)", "0"),
    ("STDEVX.P({5,9},DATE(1899,12,31)+[Value]/3)", "0.666666666666667"),
)

# Power BI's spread of one repeated inexact value is float noise no model reproduces (1.9E-07 here, ours 0), and the order Power BI walks a TOPN in
# is not the one this engine gives (STDEVX.P over TOPN differs in the 7th digit): these refuse instead of answering wrong
REFUSED_NOISE = (
    "VARX.S(Facts,DATE(2000,5,3)+1/3)",
    "STDEVX.S(Facts,TIME(22,56,42)+1/7)",
)

# Task 62 (varx-topn-52): TOPN walk order is now modelled, so these two TOPN shapes answer and match their measured Power BI answers
TOPN_MATCHED = (
    ("STDEVX.P(TOPN(3,Facts,Facts[Sales]),DATE(2020,5,19)+Facts[Quantity]*2/9)", "0.27716015393773"),
    ("STDEVX.S(TOPN(3,Facts,Facts[Sales]),DATE(2020,4,21)/1.5+Facts[Quantity])", "1.52752520563835"),
)

# a division inside an IF in the body is not a double-evaluated shape: it must stay refused
REFUSED = (
    "VARX.P(Facts,DATE(2020,1,1)+IF(Facts[Quantity]>2,1,0)/3)",
)


class DateDivisionAnswers(unittest.TestCase):
    def test_power_bi_answers_match(self):
        for expression, powerbi in ANSWERED:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")

    def test_fresh_grid_answers_match(self):
        for expression, powerbi in FRESH:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")

    def test_noise_and_unknown_order_refuse(self):
        for expression in REFUSED_NOISE:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), dax.local(expression))

    def test_topn_shapes_match_task62(self):
        for expression, powerbi in TOPN_MATCHED:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")

    def test_shape_with_a_conditional_stays_refused(self):
        for expression in REFUSED:
            with self.subTest(expression=expression):
                answer = dax.local(expression)
                self.assertTrue(answer.startswith("LOCAL-REJECT:"), answer)
                self.assertIn(REFUSAL, answer)


if __name__ == "__main__":
    unittest.main()
