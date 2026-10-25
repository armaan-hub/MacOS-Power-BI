"""Iteration 88: a CALCULATE / CALCULATETABLE inside the scalar side of a True/False filter, in any row context (compared with Power BI Desktop 2.157.879.0).

Rule (about 12,500 fresh live probes on Facts and the ZO / ZB relationship models, 0 differences; the fresh answers are frozen in
fixtures_iter88_fresh.json and replayed by test_iteration88_fixtures.py):
* A True/False CALCULATE filter is FILTER(ALL(columns), test).  A scalar `COUNTROWS(CALCULATETABLE(..tests..))` inside it is evaluated once with the
  filter columns, and the columns that its own tests read, cleared (HOIST) or once per value of the column (TRANSITION, when the scalar comes first).
* The same holds inside an iterator row context and under an outer CALCULATE.  X-iterator scalars (SUMX / MAXX over a CALCULATETABLE) hoist unchanged.
* KEEPFILTERS(test) reads like the plain test.  Several scalars in one filter, mixed readings and nested CALCULATETABLE are refused.
The expected values below are live Power BI answers."""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


POWER_BI = [
    ('SUMX(VALUES(Facts[Region]),COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")))', '9'),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>3))', '2'),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>0))', '5'),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>-1))', '6'),
    ('SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="East"),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))', '2'),
    ('SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="West"),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))', '2'),
    ('SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="North"),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))', '2'),
    ('SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="East"),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>3))', '1'),
    ('SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="East"),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>1))', '2'),
    ('SUMX(FILTER(VALUES(Facts[Region]),Facts[Region]="East"),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>0))', '3'),
    ('SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))', '4'),
    ('CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))),Facts[Region]="East")', '2'),
    ('SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))', '6'),
    ('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(Facts[Region]="East"))))', '4'),
    ('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East",Facts[Note]="Paid")))', '3'),
    ('CALCULATE(COUNTROWS(Facts),COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))<Facts[Quantity])', '4'),
]


class CalculateInRowContext(unittest.TestCase):
    def test_power_bi_answers(self) -> None:
        wrong = [(expr, answer, dax.local(expr)) for expr, answer in POWER_BI if status(answer, dax.local(expr)) != "match"]
        self.assertEqual([], wrong)

    def test_the_two_readings_inside_an_iterator(self) -> None:
        """Under SUMX the scalar still reads the filter columns of the outer context: 4 of the six quantities are above the East count of 3 rows."""
        self.assertEqual("4", dax.local('SUMX(Facts,CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))))'))
        self.assertEqual("2", dax.local('CALCULATE(CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East"))),Facts[Region]="East")'))

    def test_keepfilters_reads_like_the_plain_test(self) -> None:
        self.assertEqual("4", dax.local('CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(Facts[Region]="East"))))'))

    def test_shapes_not_established_stay_refused(self) -> None:
        for expr in (
            'CALCULATE(COUNTROWS(Facts),Facts[Quantity]=COUNTROWS(CALCULATETABLE(Facts,ALL(Facts[Quantity])))+COUNTROWS(CALCULATETABLE(Facts,NOT(Facts[Region]="East"))))',
            "CALCULATE(COUNTROWS(Facts),Facts[Quantity]<IF(ISEMPTY(CALCULATETABLE(Facts,Facts[Region]=\"East\")),1,4))",
        ):
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
