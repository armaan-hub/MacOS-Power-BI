"""Scalar math DAX functions, checked against Power BI Desktop 2.157.879.0.

Expected values were read from the running Power BI engine over ADOMD
(``tools/dax_oracle_diff.py``, iteration 64). Power BI returns doubles with about
15 significant digits, so irrational results are compared to that precision.
"""

from __future__ import annotations

from decimal import Decimal
import unittest

from analytics_studio.measures import MeasureError, evaluate_calculated_columns, evaluate_measures

HEADERS = ["Sales", "Quantity"]
ROWS = [
    {"Sales": "10.5", "Quantity": "2"},
    {"Sales": "20", "Quantity": "3"},
    {"Sales": "-1.5", "Quantity": "1"},
    {"Sales": None, "Quantity": "4"},
]


def measure(expression: str, rows=ROWS) -> Decimal | None:
    return evaluate_measures(
        [{"name": "M", "expression": expression}], rows, HEADERS, "Facts", measure_names=["M"],
    )["M"]


class ScalarMathTests(unittest.TestCase):
    def test_exact_results_match_power_bi(self) -> None:
        # (expression, Power BI result)
        for expression, expected in [
            ("INT(2.5)", 2), ("INT(-2.5)", -3), ("INT(-3)", -3), ("INT(0.9999999)", 0),
            ("TRUNC(2.789)", 2), ("TRUNC(-2.789)", -2),
            ("TRUNC(2.789, 2)", Decimal("2.78")), ("TRUNC(-2.789, 2)", Decimal("-2.78")),
            ("TRUNC(1234, -2)", 1200),
            ("SIGN(5)", 1), ("SIGN(0)", 0), ("SIGN(-0.1)", -1),
            ("SQRT(16)", 4), ("SQRT(0)", 0),
            ("EXP(0)", 1), ("LN(1)", 0),
            ("MOD(7, 3)", 1), ("MOD(-7, 3)", 2), ("MOD(7, -3)", -2),
            ("MOD(-7, -3)", -1), ("MOD(7.5, 2)", Decimal("1.5")),
            ("POWER(2, 10)", 1024), ("POWER(2, -1)", Decimal("0.5")), ("POWER(-2, 3)", -8),
            ("POWER(10, 2) + 1", 101),
        ]:
            with self.subTest(expression=expression):
                self.assertEqual(measure(expression), Decimal(str(expected)))

    def test_irrational_results_match_power_bi_to_fifteen_digits(self) -> None:
        for expression, expected in [
            ("SQRT(2)", "1.4142135623731"), ("EXP(1)", "2.71828182845905"),
            ("LN(10)", "2.30258509299405"), ("POWER(2, 0.5)", "1.4142135623731"),
        ]:
            with self.subTest(expression=expression):
                self.assertAlmostEqual(float(measure(expression)), float(expected), places=12)

    def test_math_functions_apply_to_aggregates_and_blank_aggregates(self) -> None:
        # SUM = 29, Quantity SUM = 10 over the rows above.
        self.assertEqual(measure("INT(SUM(Facts[Sales]))"), Decimal(29))
        self.assertEqual(measure("MOD(SUM(Facts[Quantity]), 4)"), Decimal(2))
        self.assertAlmostEqual(float(measure("SQRT(SUM(Facts[Quantity]))")), 3.16227766016838, places=12)
        # A blank aggregate stays blank (Power BI: INT/SQRT/SIGN/TRUNC/MOD/POWER of BLANK is BLANK).
        for function in ("INT(SUM(Facts[Sales]))", "SQRT(SUM(Facts[Sales]))", "SIGN(SUM(Facts[Sales]))",
                         "TRUNC(SUM(Facts[Sales]))", "MOD(SUM(Facts[Sales]), 3)", "POWER(SUM(Facts[Sales]), 2)"):
            with self.subTest(expression=function):
                self.assertIsNone(measure(function, [{"Sales": None, "Quantity": "1"}]))
        # EXP(BLANK()) is 1 in Power BI; a blank exponent counts as zero.
        self.assertEqual(measure("EXP(SUM(Facts[Sales]))", [{"Sales": None, "Quantity": "1"}]), Decimal(1))
        self.assertEqual(measure("POWER(2, SUM(Facts[Sales]))", [{"Sales": None, "Quantity": "1"}]), Decimal(1))

    def test_arguments_that_make_power_bi_error_are_rejected(self) -> None:
        for expression, message in [
            ("SQRT(-1)", "SQRT"), ("LN(0)", "LN"), ("LN(-1)", "LN"), ("MOD(7, 0)", "MOD"),
            ("POWER(0, 0)", "POWER"), ("POWER(0, -1)", "POWER"),
            ("POWER(-8, 0.5)", "POWER"), ("POWER(-8, 2/3)", "POWER"),  # only an exact odd root has a real result
            ("INT()", "INT"), ("INT(1, 2)", "INT"), ("MOD(1)", "MOD"), ("TRUNC(1, 2, 3)", "TRUNC"),
        ]:
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(MeasureError, message):
                    measure(expression)

    def test_trunc_digits_must_be_a_whole_number(self) -> None:
        with self.assertRaisesRegex(MeasureError, "TRUNC digits"):
            measure("TRUNC(1.2345, 1.5)")

    def test_literal_blank_arguments_follow_power_bi(self) -> None:
        # Power BI 2.157.879.0: INT/TRUNC/SIGN/SQRT/MOD/POWER of BLANK() is BLANK,
        # EXP(BLANK()) is 1 and a blank POWER exponent counts as zero.
        for expression in ("INT(BLANK())", "TRUNC(BLANK())", "SIGN(BLANK())", "SQRT(BLANK())",
                           "MOD(BLANK(), 3)", "POWER(BLANK(), 2)"):
            with self.subTest(expression=expression):
                self.assertIsNone(measure(expression))
        self.assertEqual(measure("EXP(BLANK())"), Decimal(1))
        self.assertEqual(measure("POWER(2, BLANK())"), Decimal(1))
        self.assertEqual(measure("COALESCE(INT(BLANK()), 9)"), Decimal(9))
        with self.assertRaisesRegex(MeasureError, "MOD"):  # Power BI: division by zero
            measure("MOD(7, BLANK())")
        with self.assertRaisesRegex(MeasureError, "LN"):  # Power BI returns -Infinity
            measure("LN(BLANK())")

    def test_large_operands_keep_every_digit(self) -> None:
        self.assertEqual(measure("TRUNC(5.5, 28)"), Decimal("5.5"))
        self.assertEqual(measure("TRUNC(12345.6789, 25)"), Decimal("12345.6789"))
        self.assertEqual(measure("TRUNC(1000000000000000000000000000000, 5)"), Decimal(10) ** 30)
        self.assertEqual(measure("MOD(100000000000000000000000000000, 7)"), Decimal(5))
        self.assertEqual(measure("MOD(5, 0.000000000000000000000000000001)"), Decimal(0))

    def test_results_beyond_double_range_are_rejected_like_power_bi(self) -> None:
        for expression in ("EXP(1000)", "POWER(10, 1000)", "POWER(7, 123456.789)"):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(MeasureError, "outside the supported numeric range"):
                    measure(expression)
        self.assertEqual(measure("POWER(10, 300)"), Decimal(10) ** 300)

    def test_odd_roots_of_negative_numbers_match_power_bi(self) -> None:
        # compared live with Power BI Desktop (tools/parity/dax_battery_tables2.json)
        self.assertEqual(measure("POWER(-8, 1/3)"), Decimal(-2))
        self.assertEqual(measure("POWER(-32, 0.2)"), Decimal(-2))
        self.assertEqual(measure("POWER(-8, -1/3)"), Decimal("-0.5"))
        with self.assertRaisesRegex(MeasureError, "POWER"):
            measure("POWER(-1, 4294967295)")

    def test_negative_zero_is_normalised(self) -> None:
        for expression in ("TRUNC(-0.5)", "MOD(-6, 3)", "MOD(-6, -3)", "INT(-0)", "SIGN(-0)"):
            with self.subTest(expression=expression):
                self.assertFalse(measure(expression).is_signed())

    def test_calculated_columns_use_the_same_math(self) -> None:
        _headers, rows, _types = evaluate_calculated_columns(
            [
                {"name": "Floor", "expression": "INT([Sales])"},
                {"name": "Remainder", "expression": "MOD([Quantity], 3)"},
                {"name": "Sign", "expression": "SIGN([Sales])"},
            ],
            [{"Sales": Decimal("-1.5"), "Quantity": Decimal(4)}, {"Sales": Decimal("10.5"), "Quantity": Decimal(3)}],
            HEADERS, "Facts",
        )
        self.assertEqual([row["Floor"] for row in rows], [Decimal(-2), Decimal(10)])
        self.assertEqual([row["Remainder"] for row in rows], [Decimal(1), Decimal(0)])
        self.assertEqual([row["Sign"] for row in rows], [Decimal(-1), Decimal(1)])


if __name__ == "__main__":
    unittest.main()
