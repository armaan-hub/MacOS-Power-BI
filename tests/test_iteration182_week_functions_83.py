"""Task 93 (Iteration 182): the six week time-intelligence functions (week-functions-83).

The spec file holds Power BI's live answers (no calendar objects in the guest model, so every answer is an error).
Only this test reads it; the app never does. Rule: every spec case must be refused (LOCAL-REJECT) with Power BI's
exact message after the "ERR:Query (1, N) " prefix. Nothing may crash.
"""

import json
import re
import unittest
from pathlib import Path

from analytics_studio import measures
from tools.dax_oracle_diff import local

SPEC = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-08-week-functions-83-spec.json"

WEEK_NAMES = {
    "STARTOFWEEK", "ENDOFWEEK", "NEXTWEEK", "PREVIOUSWEEK", "OPENINGBALANCEWEEK", "CLOSINGBALANCEWEEK",
}
_NAME = re.compile(r"\b(" + "|".join(sorted(WEEK_NAMES, key=len, reverse=True)) + r")\(")
_PREFIX = re.compile(r"^ERR:Query \(1, \d+\) (.*)$", re.DOTALL)


def _function_name(expression: str) -> str:
    match = _NAME.search(expression)
    return match.group(1) if match else ""


def _power_bi_message(power_bi: str) -> str:
    match = _PREFIX.match(power_bi)
    return match.group(1) if match else ""


class TestIteration182WeekFunctions83(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(SPEC.read_text(encoding="utf-8"))
        cls.cases = cls.spec["cases"]

    def test_all_six_names_are_registered(self):
        self.assertEqual(len(WEEK_NAMES), 6)
        for name in sorted(WEEK_NAMES):
            self.assertIn(name, measures.DAX_FUNCTION_NAMES, name)

    def test_spec_covers_the_six_functions(self):
        seen = {_function_name(case["expression"]) for case in self.cases}
        self.assertEqual(seen, WEEK_NAMES)

    def test_every_spec_case_is_refused_with_the_power_bi_message(self):
        for case in self.cases:
            expression, power_bi = case["expression"], case["power_bi"]
            with self.subTest(expression=expression):
                self.assertTrue(power_bi.startswith("ERR:Query (1, "), power_bi[:80])
                message = _power_bi_message(power_bi)
                self.assertTrue(message, power_bi[:80])
                loc = local(expression)
                self.assertFalse(loc.startswith("LOCAL-CRASH"), loc)
                self.assertEqual(loc, f"LOCAL-REJECT:{message}")

    def test_arity_messages_are_power_bi_wording(self):
        self.assertEqual(
            local("COUNTROWS(STARTOFWEEK())"),
            "LOCAL-REJECT:Too few arguments were passed to the STARTOFWEEK function. "
            "The minimum argument count for the function is 1.",
        )
        self.assertEqual(
            local("COUNTROWS(ENDOFWEEK(Facts[Quantity],1,2))"),
            "LOCAL-REJECT:Too many arguments were passed to the ENDOFWEEK function. "
            "The maximum argument count for the function is 1.",
        )
        self.assertEqual(
            local("OPENINGBALANCEWEEK(1)"),
            "LOCAL-REJECT:Too few arguments were passed to the OPENINGBALANCEWEEK function. "
            "The minimum argument count for the function is 2.",
        )
        self.assertEqual(
            local("CLOSINGBALANCEWEEK(1,Facts[Quantity],TRUE(),4,5)"),
            "LOCAL-REJECT:Too many arguments were passed to the CLOSINGBALANCEWEEK function. "
            "The maximum argument count for the function is 3.",
        )


if __name__ == "__main__":
    unittest.main()
