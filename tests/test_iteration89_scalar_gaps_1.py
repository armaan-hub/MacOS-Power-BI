"""Iteration 89: scalar gaps 1 (single-cell tables as scalars, DIVIDE text/Boolean alternate, LN(BLANK()), comment inside BLANK( )).

Live answers frozen from Power BI Desktop (see tools/parity/*.json and docs/plans/2026-10-26-scalar-gaps-1.md).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


POWER_BI = [
    ("{{1}}", "1"),
    ('ROW("a",1)', "1"),
    ('DATATABLE("a",INTEGER,{{1}})', "1"),
    ("COUNTROWS({{1,2},{3,4}})", "2"),
    ('DIVIDE(1,0,"x")', "x"),
    ("DIVIDE(1,0,TRUE())", "True"),
    ("LN(BLANK())", "-Infinity"),
    ("BLANK( //c\n)", "BLANK"),
]

STAYS_REFUSED = [
    'ROW("a",1,"b",2)',
    "{{1,2},{3,4}}+1",
    "{}",
    "BLANK()",
    'ROW("a",1)+1',
    'ROW("a","x")',
    'ROW("a",TRUE())',
    'ROW("a",BLANK())',
    'ROW("a",1)*ROW("b",3)',
    'ROW("a",1)=1',
    'ROW("a",1)=ROW("b",1)',
    'DIVIDE(1,0,FALSE())',
    'DIVIDE(1,0,"")',
    'DIVIDE(1,2,"x")',
    'DIVIDE(1,0,DATE(2020,1,1))',
    'LOG10(BLANK())',
    'LOG(BLANK())',
    'LOG(BLANK(),10)',
]


class ScalarGaps1Test(unittest.TestCase):
    def test_power_bi_answers(self) -> None:
        wrong = [
            (expr, answer, dax.local(expr))
            for expr, answer in POWER_BI
            if status(answer, dax.local(expr)) != "match"
        ]
        self.assertEqual([], wrong)

    def test_negative_cases_stay_refused(self) -> None:
        for expr in STAYS_REFUSED:
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT"),
                f"Expected LOCAL-REJECT for {expr}, got {res}",
            )


if __name__ == "__main__":
    unittest.main()
