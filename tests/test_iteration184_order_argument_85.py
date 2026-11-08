"""Task 95 (Iteration 184): ORDER arguments of CONCATENATEX, RANKX and ORDERBY (order-argument-85).

The spec file holds Power BI's live answers (144 cases on Facts). Only this test reads it; the app never does.
Rule: an ERR case must be refused (LOCAL-REJECT); a value case must match Power BI (same) or be refused
(LOCAL-REJECT, never a wrong value). Nothing may crash (LOCAL-CRASH).
"""

import json
import unittest
from pathlib import Path

from tools.dax_oracle_diff import local, same

SPEC = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-order-argument-85-spec.json"


class OrderArgumentSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(SPEC.read_text(encoding="utf-8"))["cases"]

    def test_every_spec_case(self):
        failures = []
        for case in self.cases:
            expression, expected = case["expression"], case["power_bi"]
            ours = local(expression)
            if ours.startswith("LOCAL-CRASH"):
                failures.append(f"CRASH {expression!r}: {ours[:120]}")
                continue
            if expected.startswith("ERR:"):
                if not ours.startswith("LOCAL-REJECT"):
                    failures.append(f"NOT REFUSED {expression!r}: local {ours[:80]!r}, Power BI {expected[:80]!r}")
                continue
            if not (same(expected, ours) or ours.startswith("LOCAL-REJECT")):
                failures.append(f"WRONG {expression!r}: local {ours[:80]!r}, Power BI {expected[:80]!r}")
        self.assertEqual(failures, [], f"{len(failures)} of {len(self.cases)} spec cases fail:\n" + "\n".join(failures[:40]))


class OrderArgumentVariableTest(unittest.TestCase):
    """Live Power BI (model ZS of tests/critic3_models.py, 2026-11-08): a variable ORDER is judged by its definition."""

    RANKX = "RANKX(ALL(ZS_Fact),ZS_Fact[Amt],50,o)"
    CONCAT = 'CONCATENATEX(ZS_Fact,ZS_Fact[Id],",",ZS_Fact[Amt],o)'
    ORDERBY = "MAXX(INDEX(1,ALL(ZS_Fact[Qty]),ORDERBY(ZS_Fact[Qty],o)),ZS_Fact[Qty])"
    ERROR = "Unexpected value for ORDER argument in {} function"

    @staticmethod
    def ours(expression):
        from tests import critic3_models

        return critic3_models.ours_for("ZS", expression)

    def test_rankx_accepted_definitions_answer_like_the_literal(self):
        for definition, expected in [("1", "8"), ("0", "3"), ("TRUE()", "8"), ("FALSE", "3"), ("1.0", "8"), ("(1)", "8")]:
            with self.subTest(definition=definition):
                self.assertEqual(self.ours(f"VAR o = {definition} RETURN {self.RANKX}"), expected)

    def test_chain_and_iterator(self):
        self.assertEqual(self.ours(f"VAR a = 1 VAR o = a RETURN {self.RANKX}"), "8")
        self.assertEqual(self.ours(f"SUMX(VALUES(ZS_Fact[Qty]), VAR o = 1 RETURN {self.RANKX})"), "48")

    def test_concatenatex_and_orderby_accepted_like_literal(self):
        for body, name in [(self.CONCAT, "c"), (self.ORDERBY, "o")]:
            for definition, literal in [("1", "1"), ("0", "0"), ("TRUE()", "1"), ("FALSE", "0")]:
                with self.subTest(body=name, definition=definition):
                    via_variable = self.ours(f"VAR o = {definition} RETURN {body}")
                    via_literal = self.ours(f"VAR o = {literal} RETURN {body}".replace(",o)", f",{literal})"))
                    self.assertFalse(via_variable.startswith("LOCAL-"), via_variable)
                    self.assertEqual(via_variable, via_literal)

    def test_other_definitions_are_power_bi_errors(self):
        for definition in ["1+0", "INT(1)", "2", '"ASC"', "BLANK()", "-1", "MAX(ZS_Fact[Qty])>0"]:
            for body, function in [(self.RANKX, "RANKX"), (self.CONCAT, "CONCATENATEX"), (self.ORDERBY, "ORDERBY")]:
                with self.subTest(definition=definition, function=function):
                    got = self.ours(f"VAR o = {definition} RETURN {body}")
                    self.assertTrue(got.startswith("LOCAL-REJECT"), got)
                    self.assertIn(self.ERROR.format(function), got)


if __name__ == "__main__":
    unittest.main()
