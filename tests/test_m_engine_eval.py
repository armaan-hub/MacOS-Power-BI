"""Tests for the Power Query M evaluator (analytics_studio.m_engine), Part B.

The 174 battery cases are Power BI Desktop's live answers. Each expression must give
exactly the same answer text from ``evaluate_to_text``. A case that Power BI rejected
with ERR:PARTITION must be a syntax error here (ERR:SYNTAX). The battery JSON is read
here in the test only; the app code never reads it.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.m_engine import evaluate_to_text

PLANS = Path(__file__).resolve().parent.parent / "docs" / "plans"
BATTERY = PLANS / "2026-11-08-m-core-battery.json"
HELDOUT = PLANS / "2026-11-09-m-core-heldout.json"
PROBES = PLANS / "2026-11-09-m-eval-probes.json"
HELDOUT2 = PLANS / "2026-11-09-m-core-heldout2.json"
ERROR_PROBES = PLANS / "2026-11-09-m-error-probes.json"
PARTITION_PREFIX = "ERR:PARTITION"
SYNTAX_PREFIX = "ERR:SYNTAX"


def _cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def _battery_cases() -> list[dict]:
    return _cases(BATTERY)


def _differences(cases: list[dict]) -> list[str]:
    """Every case whose answer text is not exactly Power BI's (ERR:PARTITION means a syntax error here)."""
    failures = []
    for index, case in enumerate(cases):
        expression = case["expression"]
        expected = case["power_bi"]
        actual = evaluate_to_text(expression)
        if expected.startswith(PARTITION_PREFIX):
            ok = actual.startswith(SYNTAX_PREFIX)
        else:
            ok = actual == expected
        if not ok:
            failures.append(f"[{index}] {expression!r}: power bi {expected!r} / ours {actual!r}")
    return failures


class BatteryTests(unittest.TestCase):
    def test_all_battery_cases_match_power_bi(self):
        cases = _battery_cases()
        self.assertEqual(len(cases), 174)
        failures = _differences(cases)
        self.assertEqual(failures, [], "\n".join(failures))

    def test_all_held_out_cases_match_power_bi(self):
        """124 further live answers, written after the first battery and never used while writing the code."""
        cases = _cases(HELDOUT)
        self.assertEqual(len(cases), 124)
        failures = _differences(cases)
        self.assertEqual(failures, [], "\n".join(failures))


class HeldOut2Tests(unittest.TestCase):
    def test_second_held_out_cases_match_power_bi(self):
        """110 further live answers, never used while writing the code (escape #(#), error detail records)."""
        cases = _cases(HELDOUT2)
        self.assertEqual(len(cases), 110)
        failures = _differences(cases)
        self.assertEqual(failures, [], "\n".join(failures))

    def test_error_record_probes_match_power_bi(self):
        """Live answers for ``try`` of built-in errors: Detail, Message.Format, Message.Parameters, ErrorCode."""
        cases = _cases(ERROR_PROBES)
        self.assertGreater(len(cases), 250)
        failures = _differences(cases)
        self.assertEqual(failures, [], "\n".join(failures))


class ProbeTests(unittest.TestCase):
    def test_probe_answers_match_power_bi(self):
        """Live answers measured while fixing the held-out differences: number text and representation,
        date/time/duration ranges, argument counts, error values, metadata, Text.Upper/Text.From, ranges,
        Table.FromRecords, List.Sum, conversions, lazy scoping."""
        cases = _cases(PROBES)
        self.assertGreater(len(cases), 900)
        failures = _differences(cases)
        self.assertEqual(failures, [], "\n".join(failures))


class NumberRuleTests(unittest.TestCase):
    """The number representation rule measured against Power BI (see the docstring of values.py)."""

    CASES = {
        # a literal a double cannot hold in 15 digits keeps its exact text until an operator touches it
        "123456789012345678": "123456789012345678",
        "-123456789012345678": "-123456789012345678",
        "3.14159265358979323846": "3.14159265358979323846",
        "100000000000000000000.0": "100000000000000000000.0",
        "1.2345678901234567e20": "123456789012345670000",
        "1e21": "1000000000000000000000",
        "1e-16": "0.0000000000000001",
        "1.5e-15": "0.0000000000000015",
        "1.000000000000000000": "1",
        "0.1234567890123456789012345678": "0.1234567890123456789012345678",
        "79228162514264337593543950336": "7.9228162514264338E+28",
        "1e29": "1E+29",
        # a double: 15 digits if they round-trip, else 17; scientific outside 1e-5 <= |v| < 1e15 for fractions
        "1e-15": "1E-15",
        "0.000001": "1E-06",
        "0.0001": "0.0001",
        "1/3": "0.33333333333333331",
        "2/3": "0.66666666666666663",
        "0.1 + 0.2": "0.30000000000000004",
        "0.1 + 0.2 - 0.3": "5.5511151231257827E-17",
        "1e15 + 0.3": "1000000000000000.3",
        "5e-324 * 1": "4.94065645841247E-324",
        # integral doubles: exact digits below 2^63, 15 digits then zeros up to the Decimal limit
        "123456789012345678 + 1": "123456789012345680",
        "123456789012345678 * 10": "1234567890123456768",
        "9223372036854775807 + 0": "9223372036854780000",
        "2147483647 * 2147483647": "4611686014132420608",
        "4294967296 * 4294967296": "18446744073709600000",
        "1e21 + 1": "1000000000000000000000",
        "8e28 + 0": "8E+28",
        "-0.0": "0",
        "0 * -1": "0",
        "1e308 * 10": "+Infinity",
    }

    def test_number_text(self):
        for expression, text in self.CASES.items():
            with self.subTest(expression=expression):
                self.assertEqual(evaluate_to_text(expression), f"V:number:{text}")

    def test_comparisons_use_the_double(self):
        for expression, expected in {
            "123456789012345678 = 123456789012345679": "true",
            "1e21 = 1e21 + 1": "true",
            "0.1 + 0.2 = 0.3": "false",
            "3.14159265358979323846 = 3.14159265358979323847": "true",
            "#nan = #nan": "false",
            "#nan < 1": "true",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(evaluate_to_text(expression), f"V:{expected}")

    def test_text_from_number(self):
        self.assertEqual(evaluate_to_text("Text.From(1e21)"), 'V:text:"1000000000000000000000"')
        self.assertEqual(evaluate_to_text("Text.From(1/3)"), 'V:text:"0.33333333333333331"')
        self.assertEqual(evaluate_to_text("Text.From(-#infinity)"), 'V:text:"-\u221e"')


class NoPythonExceptionTests(unittest.TestCase):
    def test_hostile_expressions_always_give_an_answer_text(self):
        for expression in [
            "#date(9999,12,31) + #duration(1,0,0,0)", "#date(1,1,1) - #duration(1,0,0,0)",
            "#duration(1,0,0,0) * #nan", "#duration(1,0,0,0) / 0", "{1..#nan}", "{0..2147483647}",
            "#time(0,0,#infinity)", "#datetimezone(2024,1,1,0,0,0,99999,0)", "{1}{1e300}",
            "let f = (n) => @f(n + 1) in f(0)", "Text.Upper(#nan)", "-#duration(-9223372036854775808 / 1e0, 0, 0, 0)",
            "List.Sum({#nan, 1e308})", "#binary({1e300})",
        ]:
            with self.subTest(expression=expression):
                text = evaluate_to_text(expression)
                self.assertIsInstance(text, str)
                self.assertTrue(text.startswith(("V:", "ERR:", "UNREPRESENTABLE")), text)


class LazinessAndScopeTests(unittest.TestCase):
    def test_unused_let_binding_is_never_evaluated(self):
        self.assertEqual(evaluate_to_text('let a = error "x", b = 1 in b'), "V:number:1")

    def test_recursive_let_function(self):
        self.assertEqual(evaluate_to_text("let f = (n) => if n = 0 then 1 else n * @f(n - 1) in f(4)"), "V:number:24")

    def test_record_field_refers_to_sibling(self):
        self.assertEqual(evaluate_to_text("[a = 2, b = a * 3][b]"), "V:number:6")

    def test_record_field_error_only_when_read(self):
        self.assertEqual(evaluate_to_text('[a = error "boom", b = 2][b]'), "V:number:2")

    def test_duplicate_let_name_is_error(self):
        self.assertEqual(evaluate_to_text("let x = 1, x = 2 in x"), "ERR:Expression.Error: Duplicate initializer named 'x'.")


class TryShapeTests(unittest.TestCase):
    def test_try_success_record(self):
        self.assertEqual(evaluate_to_text("try 5"), "V:record:[\"HasError\"=false,\"Value\"=number:5]")

    def test_try_error_record_has_six_error_fields(self):
        text = evaluate_to_text('try error "x"')
        self.assertTrue(text.startswith('V:record:["HasError"=true,"Error"=record:["Reason"=text:"Expression.Error"'))
        self.assertIn('"ErrorCode"=null]]', text)

    def test_try_otherwise_returns_fallback(self):
        self.assertEqual(evaluate_to_text("try 1 / 0 otherwise 9"), "V:number:+Infinity")
        self.assertEqual(evaluate_to_text('try error "x" otherwise 9'), "V:number:9")


class MetadataTests(unittest.TestCase):
    def test_metadata_does_not_change_value(self):
        self.assertEqual(evaluate_to_text('"a" meta [k = 2]'), 'V:text:"a"')

    def test_value_metadata_returns_record(self):
        self.assertEqual(evaluate_to_text('Value.Metadata(null meta [k = "v"])'), 'V:record:["k"=text:"v"]')
        self.assertEqual(evaluate_to_text("Value.Metadata(1)"), "V:record:[]")


class SyntaxErrorTests(unittest.TestCase):
    def test_syntax_error_reports_syntax(self):
        self.assertTrue(evaluate_to_text("1 +").startswith(SYNTAX_PREFIX))


if __name__ == "__main__":
    unittest.main()
