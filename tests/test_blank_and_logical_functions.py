"""Blank arithmetic, IF/ISBLANK/IFERROR/SWITCH, CEILING/FLOOR and MEDIAN/PRODUCT/COUNTBLANK.

Expected values were read from the running Power BI engine over ADOMD
(``tools/dax_oracle_diff.py``, iteration 65) against the same six-row table the
harness builds, so every number below is Power BI's answer, not an assumption.
"""

from __future__ import annotations

from decimal import Decimal
import unittest

from analytics_studio.measures import (
    MeasureError, evaluate_calculated_columns, evaluate_measures,
)

HEADERS = ["Sales", "Quantity", "Region", "Note"]
RAW = [
    ("10.5", "2", "East", "Paid"),
    ("20", "3", "West", ""),
    ("-1.5", "1", "East", "Paid"),
    ("", "4", "North", "Late"),
    ("0", "0", "West", "Paid"),
    ("2.5", "5", "East", ""),
]
ROWS = [{h: (v if v != "" else None) for h, v in zip(HEADERS, row)} for row in RAW]
CONTEXT = [{
    "id": "facts", "name": "Facts", "headers": HEADERS, "rows": ROWS,
    "column_types": {
        "Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text",
    },
}]


def measure(expression: str) -> Decimal | None:
    return evaluate_measures(
        [{"name": "M", "expression": expression}], ROWS, HEADERS, "Facts",
        measure_names=["M"], table_context=CONTEXT, active_table_id="facts",
    )["M"]


class BlankArithmeticTests(unittest.TestCase):
    def test_blank_arithmetic_matches_power_bi(self) -> None:
        for expression, expected in [
            ("BLANK() + 1", 1), ("BLANK() - 1", -1), ("1 - BLANK()", 1),
            ("BLANK() * 5", None), ("0 * BLANK()", None), ("BLANK() / 2", None),
            ("BLANK() / 0", None), ("BLANK() / BLANK()", None),
            ("BLANK() + BLANK()", None), ("-BLANK()", None),
            ("SUM(Facts[Sales]) + BLANK()", Decimal("31.5")),
            ("IF(BLANK() + BLANK() = 0, 1, 2)", 1),
            ("IF(BLANK() = BLANK(), 1, 2)", 1), ("IF(BLANK() = 0, 1, 2)", 1),
            ("IF(0 = BLANK(), 1, 2)", 1), ("IF(BLANK() < 1, 1, 2)", 1),
        ]:
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), None if expected is None else Decimal(expected))

    def test_division_by_blank_or_zero_is_infinity_or_nan(self) -> None:
        # Verified live: 2/BLANK() and 1/0 are Infinity, -1/0 is -Infinity, 0/0 and 0/BLANK() are NaN.
        for expression, expected in (
            ("2 / BLANK()", Decimal("Infinity")), ("1 / 0", Decimal("Infinity")), ("-1 / 0", Decimal("-Infinity")),
            ("SUM(Facts[Sales]) / 0", Decimal("Infinity")),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), expected)
        for expression in ("0 / BLANK()", "0 / 0", "1/0*0", "1/0-1/0"):
            with self.subTest(expression=expression):
                self.assertTrue(measure(expression).is_nan())

    def test_blank_survives_calculated_column_arithmetic(self) -> None:
        _headers, rows, _types = evaluate_calculated_columns(
            [{"name": "Double", "expression": "[Sales] * 2"},
             {"name": "Shifted", "expression": "[Sales] + BLANK()"}],
            ROWS, HEADERS, "Facts",
        )
        self.assertEqual(rows[3]["Double"], None)  # blank * 2 is blank
        self.assertEqual(rows[3]["Shifted"], None)  # blank + blank is blank
        self.assertEqual(rows[0]["Double"], Decimal("21.0"))
        self.assertEqual(rows[0]["Shifted"], Decimal("10.5"))


class ConditionalFunctionTests(unittest.TestCase):
    def test_if_isblank_iferror_switch_match_power_bi(self) -> None:
        for expression, expected in [
            ("IF(ISBLANK(BLANK()), 1, 2)", 1), ("IF(ISBLANK(0), 1, 2)", 2),
            ("IF(ISBLANK(SUM(Facts[Sales])), 1, 2)", 2),
            ("IF(ISBLANK(SUM(Facts[Sales]) - SUM(Facts[Sales])), 1, 2)", 2),
            ("IF(NOT(ISBLANK(BLANK())), 1, 2)", 2),
            ("IF(ISBLANK(BLANK()) && TRUE(), 1, 2)", 1),
            ("IF(ISBLANK(SUM(Facts[Sales])), 0, SUM(Facts[Sales]) * 2)", 63),
            ("IF(TRUE(), 1)", 1), ("IF(FALSE(), 1)", None), ("IF(BLANK(), 1)", None),
            ("IF(BLANK(), 1, 2)", 2), ("IF(SUM(Facts[Sales]) > 100, 1)", None),
            ("IF(SUM(Facts[Sales]) > 10, 1)", 1),
            ("IFERROR(1 / 0, -1)", -1), ("IFERROR(5, -1)", 5), ("IFERROR(BLANK(), -1)", None),
            ("IFERROR(SQRT(-1), 7)", 7), ("IFERROR(LN(0), 7)", 7), ("IFERROR(0 / 0, 3)", 3),
            ("IFERROR(DIVIDE(1, 0), 7)", None), ("IFERROR(1 / 0, BLANK())", None),
            ("IFERROR(SUM(Facts[Sales]) / 0, 9)", 9),
            ("IFERROR(IFERROR(1 / 0, SQRT(-1)), 4)", 4), ("IFERROR(IFERROR(1 / 0, 5), 4)", 5),
            ("IFERROR(SUM(Facts[Sales]), 0)", Decimal("31.5")),
            ("COALESCE(IFERROR(1 / 0, BLANK()), 9)", 9),
            ("CALCULATE(IFERROR(SUM(Facts[Sales]) / 0, 0))", 0),
            ("SWITCH(2, 1, 10, 2, 20, 30)", 20), ("SWITCH(5, 1, 10, 2, 20, 30)", 30),
            ("SWITCH(5, 1, 10, 2, 20)", None), ("SWITCH(2, 1, 10)", None),
            ("SWITCH(TRUE(), 1 > 2, 10, 2 > 1, 20, 30)", 20),
            ("SWITCH(TRUE(), SUM(Facts[Sales]) > 100, 1, SUM(Facts[Sales]) > 10, 2, 3)", 2),
            ("SWITCH(BLANK(), 0, 10, 20)", 20), ("SWITCH(0, BLANK(), 10, 20)", 20),
            ("SWITCH(1, 1, BLANK(), 2)", None), ("SWITCH(TRUE(), BLANK(), 1, 2)", 2),
            ("SWITCH(SUM(Facts[Quantity]), 0, 1, 2)", 2),
            ("SWITCH(1, 2, 1 / 0, 1, 7)", 7),  # an unmatched branch is never evaluated
        ]:
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), None if expected is None else Decimal(expected))

    def test_switch_rejects_mixed_true_false_and_number_like_power_bi(self) -> None:
        for expression in ("SWITCH(1, TRUE(), 5, 9)", "SWITCH(TRUE(), 1, 5, 9)", "SWITCH(1)"):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    measure(expression)

    def test_iferror_does_not_swallow_unsupported_syntax(self) -> None:
        # Only data errors fall through to the alternate; a formula the engine cannot
        # run must still be reported instead of silently turning into the fallback.
        with self.assertRaises(MeasureError):
            measure("IFERROR(NOSUCHFUNCTION(1), 5)")
        with self.assertRaises(MeasureError):
            measure("IFERROR(SUM(Facts[Missing]), 5)")

    def test_infinity_reaches_comparisons_like_power_bi(self) -> None:
        # Verified live: 1/0 is Infinity, so it compares (1/0>1 is True) instead of being an error.
        for expression, expected in (
            ("IFERROR(1 / 0 > 1, 2)", True), ("IFERROR(IF(1 / 0 > 1, 1, 2), 5)", 1),
            ("IFERROR(IF(ISBLANK(1 / 0), 1, 2), 5)", 2), ("IFERROR(SWITCH(1 / 0, 1, 1, 2), 5)", 2),
            ("0/0 = 0/0", False), ("0/0 <> 0/0", True), ("1/0 = 1/0", True), ("IF(0/0 > 1, 1, 2)", 2),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), expected)

    def test_conditionals_work_in_calculated_columns(self) -> None:
        _headers, rows, _types = evaluate_calculated_columns(
            [{"name": "Safe", "expression": "IFERROR(10 / [Quantity], -1)"},
             {"name": "Band", "expression": "SWITCH(TRUE(), [Sales] > 10, 3, [Sales] > 0, 2, 1)"},
             {"name": "Flag", "expression": "IF(ISBLANK([Sales]), 1)"}],
            ROWS, HEADERS, "Facts",
        )
        self.assertEqual([row["Safe"] for row in rows][4], Decimal(-1))  # Quantity 0
        self.assertEqual([row["Safe"] for row in rows][0], Decimal(5))
        self.assertEqual([row["Band"] for row in rows], [3, 3, 1, 1, 1, 2])
        self.assertEqual([row["Flag"] for row in rows], [None, None, None, 1, None, None])


class RoundToMultipleTests(unittest.TestCase):
    def test_ceiling_and_floor_match_power_bi(self) -> None:
        for expression, expected in [
            ("CEILING(2.1, 1)", 3), ("CEILING(-2.1, 1)", -2), ("CEILING(2.1, 0.5)", Decimal("2.5")),
            ("CEILING(2.1, 2)", 4), ("CEILING(7, 3)", 9), ("CEILING(10, 3)", 12),
            ("CEILING(-10, 3)", -9), ("CEILING(0, 1)", 0), ("CEILING(0, -1)", 0),
            ("CEILING(0, 0)", 0), ("CEILING(5, 0)", 0), ("CEILING(-5, 0)", 0),
            ("CEILING(2.1, BLANK())", 0), ("CEILING(BLANK(), 1)", None),
            ("CEILING(BLANK(), 0)", None), ("CEILING(-2.1, -1)", -3),
            ("CEILING(-2.1, -0.5)", Decimal("-2.5")), ("CEILING(0.3, 0.1)", Decimal("0.3")),
            ("CEILING(1.1, 0.1)", Decimal("1.1")), ("CEILING(2.5, 0.3)", Decimal("2.7")),
            ("CEILING(123456.789, 0.01)", Decimal("123456.79")),
            ("FLOOR(2.9, 1)", 2), ("FLOOR(-2.1, 1)", -3), ("FLOOR(2.9, 0.5)", Decimal("2.5")),
            ("FLOOR(7, 3)", 6), ("FLOOR(10, 3)", 9), ("FLOOR(-10, 3)", -12),
            ("FLOOR(0, 0)", 0), ("FLOOR(0, -1)", 0), ("FLOOR(BLANK(), 1)", None),
            ("FLOOR(BLANK(), 0)", None), ("FLOOR(-2.1, -1)", -2), ("FLOOR(-2.1, -0.5)", -2),
            ("FLOOR(0.3, 0.1)", Decimal("0.3")), ("FLOOR(2.5, 0.3)", Decimal("2.4")),
        ]:
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), None if expected is None else Decimal(expected))

    def test_errors_power_bi_raises(self) -> None:
        for expression in (
            "CEILING(2.1, -1)", "FLOOR(2.1, -1)", "FLOOR(5, 0)", "FLOOR(-5, 0)",
            "FLOOR(2.9, 0)", "FLOOR(2.9, BLANK())", "CEILING(2.1)", "FLOOR(2.9)",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    measure(expression)

    def test_results_are_exact_decimals_not_floats(self) -> None:
        self.assertEqual(measure("CEILING(0.3, 0.1)"), Decimal("0.3"))
        self.assertEqual(str(measure("FLOOR(0.3, 0.1)")), "0.3")

    def test_iferror_catches_floor_errors(self) -> None:
        self.assertEqual(measure("IFERROR(FLOOR(5, 0), 99)"), Decimal(99))


class ColumnAggregateTests(unittest.TestCase):
    def test_median_product_countblank_match_power_bi(self) -> None:
        for expression, expected in [
            ("MEDIAN(Facts[Sales])", Decimal("2.5")), ("MEDIAN(Facts[Quantity])", Decimal("2.5")),
            ("PRODUCT(Facts[Quantity])", 0), ("PRODUCT(Facts[Sales])", 0),
            ("COUNTBLANK(Facts[Note])", 2), ("COUNTBLANK(Facts[Sales])", 1),
            ("COUNTBLANK(Facts[Region])", None), ("COUNTBLANK(Facts[Quantity])", None),
            ("MEDIAN(Facts[Sales]) + 1", Decimal("3.5")), ("PRODUCT(Facts[Quantity]) + 1", 1),
        ]:
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), None if expected is None else Decimal(expected))

    def test_median_of_odd_count_and_product_of_nonzero(self) -> None:
        rows = [{"Sales": v, "Quantity": "1", "Region": "x", "Note": "n"} for v in ("3", "1", "2")]
        for expression, expected in (("MEDIAN(Facts[Sales])", 2), ("PRODUCT(Facts[Sales])", 6)):
            with self.subTest(expression=expression):
                result = evaluate_measures(
                    [{"name": "M", "expression": expression}], rows, HEADERS, "Facts",
                    measure_names=["M"],
                )["M"]
                self.assertEqual(result, Decimal(expected))

    def test_product_overflow_is_an_error(self) -> None:
        rows = [{"Sales": "1E200", "Quantity": "1", "Region": "x", "Note": "n"}] * 3
        with self.assertRaises(MeasureError):
            evaluate_measures(
                [{"name": "M", "expression": "PRODUCT(Facts[Sales])"}], rows, HEADERS, "Facts",
                measure_names=["M"],
            )


class CriticRegressionTests(unittest.TestCase):
    """Defects an adversarial review reproduced; each answer below was confirmed against Power BI."""

    def test_negative_zero_shows_as_zero(self) -> None:
        for expression in ("0*-1", "PRODUCT(Facts[Sales])", "-0.0/5"):
            with self.subTest(expression=expression):
                result = measure(expression)
                self.assertEqual(result, 0)
                self.assertFalse(result.is_signed())

    def test_calculated_column_negative_zero_shows_as_zero(self) -> None:
        _headers, rows, _types = evaluate_calculated_columns(
            [{"name": "Z", "expression": "[Sales] * 0 * -1"}], ROWS, HEADERS, "Facts",
        )
        self.assertEqual(rows[0]["Z"], 0)
        self.assertFalse(rows[0]["Z"].is_signed())

    def test_arithmetic_beyond_the_double_range_is_infinity_not_a_number(self) -> None:
        self.assertEqual(measure("1E308*10"), Decimal("Infinity"))
        self.assertEqual(measure("1E308+1E308"), Decimal("Infinity"))
        self.assertEqual(measure("-1E308*10"), Decimal("-Infinity"))
        self.assertTrue(measure("SUMX(Facts,Facts[Sales]*1E200*1E200)").is_nan())  # Infinity + -Infinity
        self.assertEqual(measure("IFERROR(1E308+1E308,3)"), 3)

    def test_iterators_accept_the_conditional_functions(self) -> None:
        for expression, expected in (
            ("MAXX(Facts,IF(Facts[Sales]>0,Facts[Sales]))", 20),
            ("MINX(Facts,IF(Facts[Sales]>0,Facts[Sales],0))", 0),
            ("COUNTX(Facts,IFERROR(Facts[Sales]/Facts[Quantity],0))", 5),
            ("MAXX(Facts,SWITCH(TRUE(),Facts[Sales]>5,1,0))", 1),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), Decimal(expected))

    def test_blank_only_flows_where_power_bi_gives_blank(self) -> None:
        self.assertIsNone(measure("IF(TRUE(),ABS(BLANK()),1)"))
        self.assertIsNone(measure("IF(TRUE(),CALCULATE(BLANK()),1)"))
        # verified live: ROUND(BLANK(),0) is blank and a blank digits argument counts as 0
        self.assertIsNone(measure("IF(TRUE(),ROUND(BLANK(),0),1)"))
        self.assertEqual(measure("ROUND(2.5,BLANK())"), 3)
        self.assertEqual(measure("SUMX(Facts,ROUND(Facts[Sales],BLANK()))"), 32)

    def test_division_by_zero_used_as_a_condition_is_true_like_power_bi(self) -> None:
        # Verified live: Infinity (and NaN) count as TRUE in a condition.
        for expression, expected in (
            ("IFERROR(IF(1/0,1,2),9)", 1), ("IFERROR(IF(NOT(1/0),1,2),9)", 2), ("AND(1/0,1)", True),
            ("OR(1/0,0)", True), ("NOT(1/0)", False), ("IF(0/0,1,2)", 1),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), expected)
        self.assertEqual(measure("IFERROR(1/0,2)"), 2)

    def test_ceiling_of_a_huge_number_is_not_below_the_number(self) -> None:
        from analytics_studio.measures import _round_to_multiple

        self.assertGreaterEqual(_round_to_multiple("CEILING", Decimal("1E100"), Decimal(3)), Decimal("1E100"))
        self.assertLessEqual(_round_to_multiple("FLOOR", Decimal("1E100"), Decimal(3)), Decimal("1E100"))


if __name__ == "__main__":
    unittest.main()
