"""Task 94 (Iteration 183): the 14 visual-calculation functions outside a visual calculation (visual-calc-names-84).

The spec file holds Power BI's live answers (210 cases, all errors). Only this test reads it; the app never does.
Rule: every spec case must be refused (LOCAL-REJECT) with Power BI's exact message after the optional
"Query (1, N) " position prefix. Nothing may crash.
"""

import json
import re
import unittest
from pathlib import Path

from analytics_studio import measures
from tools.dax_oracle_diff import local

SPEC = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-visual-calc-names-84-spec.json"

VISUAL_CALC_NAMES = {
    "RUNNINGSUM", "MOVINGAVERAGE", "FIRST", "LAST", "NEXT", "PREVIOUS", "RANGE", "LOOKUP",
    "LOOKUPWITHTOTALS", "EXPAND", "EXPANDALL", "COLLAPSE", "COLLAPSEALL", "ISATLEVEL",
}
_NAME = re.compile(r"\b(" + "|".join(sorted(VISUAL_CALC_NAMES, key=len, reverse=True)) + r")\(")
_ERR = re.compile(r"^ERR:(?:Query \(1, \d+\) )?(.*)$", re.DOTALL)
_VISUAL_ONLY = "can only be used in the expression of a visual calculation."


def _function_name(expression: str) -> str:
    match = _NAME.search(expression)
    return match.group(1) if match else ""


def _power_bi_message(power_bi: str) -> str:
    match = _ERR.match(power_bi)
    return match.group(1) if match else ""


class TestIteration183VisualCalcNames84(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(SPEC.read_text(encoding="utf-8"))
        cls.cases = cls.spec["cases"]

    def test_all_fourteen_names_are_registered(self):
        self.assertEqual(len(VISUAL_CALC_NAMES), 14)
        for name in sorted(VISUAL_CALC_NAMES):
            self.assertIn(name, measures.DAX_FUNCTION_NAMES, name)

    def test_spec_covers_the_fourteen_functions(self):
        seen = {_function_name(case["expression"]) for case in self.cases}
        self.assertEqual(seen, VISUAL_CALC_NAMES)

    def test_every_spec_case_is_refused_with_the_power_bi_message(self):
        for case in self.cases:
            expression, power_bi = case["expression"], case["power_bi"]
            with self.subTest(expression=expression):
                self.assertTrue(power_bi.startswith("ERR:"), power_bi[:80])
                message = _power_bi_message(power_bi)
                self.assertTrue(message, power_bi[:80])
                loc = local(expression)
                self.assertFalse(loc.startswith("LOCAL-CRASH"), loc)
                self.assertEqual(loc, f"LOCAL-REJECT:{message}")

    def test_arity_messages_are_power_bi_wording(self):
        self.assertEqual(
            local("COUNTROWS(MOVINGAVERAGE(1))"),
            "LOCAL-REJECT:Too few arguments were passed to the MOVINGAVERAGE function. "
            "The minimum argument count for the function is 2.",
        )
        self.assertEqual(
            local("ISATLEVEL(1,2)"),
            "LOCAL-REJECT:Too many arguments were passed to the ISATLEVEL function. "
            "The maximum argument count for the function is 1.",
        )
        self.assertEqual(
            local("EXPANDALL(1,2,3)"),
            "LOCAL-REJECT:Too many arguments were passed to the EXPANDALL function. "
            "The maximum argument count for the function is 2.",
        )

    def test_lookupwithtotals_column_reference_message(self):
        self.assertEqual(
            local("LOOKUPWITHTOTALS(SUM(Facts[Sales]),2)"),
            "LOCAL-REJECT:Function LOOKUPWITHTOTALS expects a column reference as argument number 2.",
        )

    def test_bare_words_are_not_visual_calls(self):
        # A name not written as a call keeps its old meaning (a table or identifier), never the visual-calc message.
        for expression in ("COUNTROWS(First)", "COUNTROWS(Last)", "COUNTROWS(Next)", "COUNTROWS(Range)"):
            with self.subTest(expression=expression):
                loc = local(expression)
                self.assertFalse(loc.startswith("LOCAL-CRASH"), loc)
                self.assertNotIn(_VISUAL_ONLY, loc)


if __name__ == "__main__":
    unittest.main()
