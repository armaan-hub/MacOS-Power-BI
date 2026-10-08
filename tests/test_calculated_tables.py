"""Unit checks for the supported local calculated-table expression subset."""

from __future__ import annotations

import unittest

from analytics_studio.file_import import ImportCandidate
from analytics_studio.measures import (
    MeasureError,
    evaluate_calculated_table,
    normalize_calculated_table_expression,
)


class CalculatedTableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = ImportCandidate(
            kind="csv",
            headers=["Region", "Amount"],
            rows=[
                {"Region": "West", "Amount": "10"},
                {"Region": "East", "Amount": "20"},
                {"Region": "West", "Amount": "30"},
                {"Region": "", "Amount": "40"},
                {"Region": "", "Amount": "50"},
            ],
            options={},
            notices=[],
        )

    def test_distinct_table_preserves_first_seen_values_and_one_blank(self) -> None:
        expression = "DISTINCT('Sales'[Region])"

        headers, rows = evaluate_calculated_table(
            expression, self.candidate, "Sales"
        )

        self.assertEqual(headers, ["Region"])
        self.assertEqual(rows, [
            {"Region": "West"},
            {"Region": "East"},
            {"Region": ""},
        ])

    def test_expression_must_be_distinct_on_the_selected_source_column(self) -> None:
        with self.assertRaisesRegex(MeasureError, "DISTINCT"):
            normalize_calculated_table_expression(
                "SUM('Sales'[Amount])", "Sales", self.candidate.headers
            )
        with self.assertRaisesRegex(MeasureError, "selected source table"):
            normalize_calculated_table_expression(
                "DISTINCT('Other'[Region])", "Sales", self.candidate.headers
            )
        with self.assertRaisesRegex(MeasureError, "does not exist"):
            normalize_calculated_table_expression(
                "DISTINCT('Sales'[Missing])", "Sales", self.candidate.headers
            )


if __name__ == "__main__":
    unittest.main()
