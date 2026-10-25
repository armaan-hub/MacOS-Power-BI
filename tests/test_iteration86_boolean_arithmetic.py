"""Iteration 86: a Boolean inside arithmetic, INT or ABS in COUNTX / COUNTAX / MAXX / MINX.

fixtures_iter86_boolean_arithmetic.json: saved live Power BI answers (tools/parity, dax_battery_comments_booleans and neighbours) that the local
engine used to refuse ("Iterator arithmetic comparisons need numeric operands", "Iterator INT argument 1 needs a numeric expression").  Power BI
turns a Boolean into 1 / 0 in + - * / unary minus, INT and ABS: SUMX, AVERAGEX, PRODUCTX, MEDIANX, GEOMEANX, STDEVX, VARX of the same expressions
already matched Power BI, only the four iterators whose result type is checked first refused them.  They must now match exactly.

What stays refused (not established): a Boolean in any other numeric function (ROUND, SQRT, ...), text in arithmetic, and a bare Boolean result
(COUNTX(Facts, Facts[Quantity] > 1) is an error in Power BI, which the engine reports as an error too)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

HERE = Path(__file__).parent
SAVED = json.loads((HERE / "fixtures_iter86_boolean_arithmetic.json").read_text())
FRESH = json.loads((HERE / "fixtures_iter86_boolean_fresh.json").read_text())["items"]


class BooleanArithmeticInIterators(unittest.TestCase):
    def test_fresh_probes_match_or_are_refused(self) -> None:
        """900 live probes written for this slice (Booleans in + - * / ^, unary minus, INT, ABS, ROUND, SQRT, in six iterators, plain, over FILTER, under
        CALCULATE and over ADDCOLUMNS): 881 match, 19 are refused, none may be answered differently."""
        wrong = []
        for _model, expr, powerbi, _old, _state in FRESH:
            ours = dax.local(expr)
            state = status(powerbi, ours)
            if state not in {"match", "gap-reject"}:
                wrong.append((state, expr, powerbi[:60], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(FRESH)} fresh probes answered wrongly")

    def test_saved_power_bi_answers_now_match(self) -> None:
        wrong = []
        for row in SAVED:
            ours = dax.local(row["expr"])
            if status(row["powerbi"], ours) != "match":
                wrong.append((row["expr"], row["powerbi"][:40], ours[:60]))
        self.assertEqual([], wrong[:5], f"{len(wrong)} of {len(SAVED)} saved answers do not match")

    def test_the_rule_spelled_out(self) -> None:
        """Live Power BI on the six-row Facts table: Quantity > 1 is TRUE for four rows."""
        facts = dax.local
        self.assertEqual("6", facts("COUNTX(Facts,(Facts[Quantity]>1)*1)"))
        self.assertEqual("1", facts("MAXX(Facts,(Facts[Quantity]>1)+0)"))
        self.assertEqual("-1", facts("MINX(Facts,-(Facts[Quantity]>1))"))
        self.assertEqual("0", facts("MINX(Facts,ABS(Facts[Quantity]>1))"))
        self.assertEqual("6", facts("COUNTAX(Facts,INT(Facts[Quantity]>1))"))

    def test_other_shapes_are_not_widened(self) -> None:
        # a bare Boolean result is still an error / refusal, and so is text in arithmetic
        self.assertTrue(dax.local("COUNTX(Facts,Facts[Quantity]>1)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local('MAXX(Facts,(Facts[Quantity]>1)+"x")').startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
