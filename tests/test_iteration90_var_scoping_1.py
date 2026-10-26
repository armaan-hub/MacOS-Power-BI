"""Iteration 90: var scoping 1 (nested VAR blocks, table VAR in COUNTROWS, VAR in a CALCULATE filter, bare CR ends a line comment).

Live answers frozen from Power BI Desktop (see tools/parity/*.json and docs/plans/2026-10-26-var-scoping-1.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status


POWER_BI = [
    ("VAR x=1 RETURN VAR x=2 RETURN x", "2"),
    ("VAR x=1 RETURN x+VAR y=2 RETURN y", "3"),
    ("VAR t=Facts RETURN COUNTROWS(t)", "6"),
    ("VAR a = 1 // x\rRETURN a", "1"),
    ("VAR a = 1 -- x\rRETURN a", "1"),
    ("CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity] RETURN t>2)", "3"),
    ("CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN Facts[Quantity]>t)", "3"),
]

STAYS_REFUSED = [
    "VAR x=1 VAR x=2 RETURN x",
    "VAR t=Facts RETURN t",
    "VAR t=Facts RETURN IF(FALSE(),t,1)",
    "VAR t=Facts RETURN SUMX(t,1)",
    "VAR t=Facts RETURN COUNTROWS(FILTER(t,TRUE()))",
    "CALCULATE(COUNTROWS(Facts),VAR t = SUM(Facts[Quantity]) RETURN Facts[Quantity]+t>16)",
    "CALCULATE(COUNTROWS(Facts),VAR t = CALCULATE(SUM(Facts[Quantity])) RETURN Facts[Quantity]+t>16)",
    "CALCULATE(COUNTROWS(Facts),VAR t = Facts[Quantity]+1 RETURN t>2)",
]


class VarScoping1Test(unittest.TestCase):
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

    def test_whole_saved_battery_never_differs(self) -> None:
        """tools/parity/dax_battery_var_scoping.json: 90 live answers (shadowing in a CALCULATE filter, KEEPFILTERS as a VAR RETURN,
        operators before VAR, CR comments ...). The app may refuse a shape Power BI answers, but must never answer differently."""
        saved = json.loads((Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_var_scoping.json").read_text())
        bad = [
            (item["expr"], item["powerbi"], dax.local(item["expr"]))
            for item in saved["items"]
            if status(item["powerbi"], dax.local(item["expr"])) in {"DIFF", "CRASH"}
        ]
        self.assertEqual([], bad)


if __name__ == "__main__":
    unittest.main()
