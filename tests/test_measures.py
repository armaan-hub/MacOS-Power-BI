"""Safety and arithmetic tests for the local DAX measure subset."""

from __future__ import annotations

from decimal import Decimal
import unittest

from analytics_studio.measures import (
    MeasureError,
    evaluate_measures,
    normalize_measure,
    validate_measures,
)
from analytics_studio.project import FORMAT_VERSION, ProjectFileError, new_project, validate_project


class MeasureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.headers = ["Sales", "Quantity", "Region", "Note"]
        self.rows = [
            {"Sales": "10.5", "Quantity": "2", "Region": "East", "Note": "Paid"},
            {"Sales": "20", "Quantity": "3", "Region": "West", "Note": ""},
            {"Sales": "-1.5", "Quantity": "1", "Region": "East", "Note": "Paid"},
        ]

    def test_aggregations_arithmetic_and_measure_dependencies(self) -> None:
        measures = [
            {"name": "Gross sales", "expression": "SUM([Sales])"},
            {"name": "Average sale", "expression": "AVERAGE([Sales])"},
            {"name": "Rate", "expression": "DIVIDE([Gross sales], COUNTROWS())"},
            {"name": "Double rate", "expression": "[Rate] * 2"},
        ]

        result = evaluate_measures(measures, self.rows, self.headers, "Sales data")

        self.assertEqual(result["Gross sales"], Decimal("29.0"))
        self.assertEqual(result["Average sale"], Decimal("9.666666666666666666666666667"))
        self.assertEqual(result["Rate"], Decimal("29.0") / 3)
        self.assertEqual(result["Double rate"], Decimal("29.0") / 3 * 2)

    def test_count_text_distinct_count_and_empty_divide_alternate(self) -> None:
        measures = [
            {"name": "Rows", "expression": "COUNTROWS()"},
            {"name": "Notes", "expression": "COUNTA([Note])"},
            {"name": "Unique regions", "expression": "DISTINCTCOUNT([Region])"},
            {"name": "Safe rate", "expression": "DIVIDE(10, 0, -1)"},
        ]

        result = evaluate_measures(measures, self.rows, self.headers)

        self.assertEqual(result["Rows"], Decimal(3))
        self.assertEqual(result["Notes"], Decimal(2))
        self.assertEqual(result["Unique regions"], Decimal(2))
        self.assertEqual(result["Safe rate"], Decimal(-1))

    def test_abs_and_round_use_safe_decimal_evaluation_and_dax_half_away_rounding(self) -> None:
        result = evaluate_measures([
            {"name": "Absolute loss", "expression": "ABS(MIN([Sales]))"},
            {"name": "Rounded average", "expression": "ROUND(AVERAGE([Sales]), 2)"},
            {"name": "Round positive half", "expression": "ROUND(2.5, 0)"},
            {"name": "Round negative half", "expression": "ROUND(-2.5, 0)"},
            {"name": "Round tens", "expression": "ROUND(125, -1)"},
        ], self.rows, self.headers)

        self.assertEqual(result["Absolute loss"], Decimal("1.5"))
        self.assertEqual(result["Rounded average"], Decimal("9.67"))
        self.assertEqual(result["Round positive half"], Decimal("3"))
        self.assertEqual(result["Round negative half"], Decimal("-3"))
        self.assertEqual(result["Round tens"], Decimal("1.3E+2"))

    def test_abs_and_round_reject_bad_arity_and_fractional_precision(self) -> None:
        for expression in (
            "ABS()", "ABS(1, 2)", "ROUND(1)", "ROUND(1, 1.5)", "ROUND(1, 29)"
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        self.rows,
                        self.headers,
                    )

    def test_if_comparisons_and_logical_expressions(self) -> None:
        result = evaluate_measures([
            {"name": "Threshold", "expression": "IF(SUM([Sales]) >= 20, SUM([Sales]), 0)"},
            {"name": "Fallback", "expression": "IF(SUM([Sales]) < 0, ABS(SUM([Sales])), ROUND(AVERAGE([Sales]), 2))"},
            {"name": "And condition", "expression": "IF(AND(COUNTROWS() = 3, SUM([Sales]) <> 0), 1, 0)"},
            {"name": "Or condition", "expression": "IF(SUM([Sales]) < 0 || COUNTROWS() > 2, 1, 0)"},
            {"name": "Not condition", "expression": "IF(NOT(SUM([Sales]) < 0), 1, 0)"},
            {"name": "Boolean comparison", "expression": "IF(TRUE = FALSE, 1, 0)"},
        ], self.rows, self.headers)

        self.assertEqual(result["Threshold"], Decimal("29.0"))
        self.assertEqual(result["Fallback"], Decimal("9.67"))
        self.assertEqual(result["And condition"], Decimal(1))
        self.assertEqual(result["Or condition"], Decimal(1))
        self.assertEqual(result["Not condition"], Decimal(1))
        self.assertEqual(result["Boolean comparison"], Decimal(0))

    def test_conditional_expressions_reject_invalid_boolean_shapes(self) -> None:
        for expression in (
            "IF(1 = 1, 2)",
            "1 < 2 < 3",
            "SUM([Sales]) > 10",
            "IF(TRUE, FALSE, TRUE) + 1",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        self.rows,
                        self.headers,
                    )

    def test_sumx_and_averagex_evaluate_row_expressions_with_blank_handling(self) -> None:
        measures = [
            {"name": "Line total", "expression": "SUMX('Active table', [Sales] * [Quantity])"},
            {"name": "Qualified line total", "expression": "SUMX('Active table', 'Active table'[Sales] * [Quantity])"},
            {"name": "Average sales", "expression": "AVERAGEX('Active table', [Sales])"},
        ]
        rows = [*self.rows, {"Sales": "", "Quantity": "4", "Region": "East", "Note": ""}]

        result = evaluate_measures(measures, rows, self.headers)

        self.assertEqual(result["Line total"], Decimal("79.5"))
        self.assertEqual(result["Qualified line total"], Decimal("79.5"))
        self.assertEqual(result["Average sales"], Decimal("9.666666666666666666666666667"))

    def test_iterators_reject_unloaded_tables_text_and_measure_context_transition(self) -> None:
        for expression, message in (
            ("SUMX(Missing, [Sales])", "not loaded"),
            ("SUMX('Active table', [Note])", "non-numeric"),
            
        ):
            with self.subTest(expression=expression):
                measures = [{"name": "Base", "expression": "SUM([Sales])"}]
                if "[Base]" not in expression:
                    measures = [{"name": "Invalid", "expression": expression}]
                else:
                    measures.append({"name": "Invalid", "expression": expression})
                with self.assertRaisesRegex(MeasureError, message):
                    evaluate_measures(measures, self.rows, self.headers, measure_names=["Invalid"])

    def test_qualified_column_and_formula_assignment_are_supported(self) -> None:
        measure = normalize_measure(
            "Net sales", "Net sales = SUM('Sales data'[Sales]) - SUM([Sales]) + 29"
        )

        self.assertEqual(measure, {
            "name": "Net sales",
            "expression": "SUM('Sales data'[Sales]) - SUM([Sales]) + 29",
        })
        self.assertEqual(
            evaluate_measures([measure], self.rows, self.headers, "Sales data")["Net sales"],
            Decimal(29),
        )

    def test_invalid_dax_and_unsafe_code_are_rejected(self) -> None:
        for expression in (
            "SUM([Missing])",
            "__import__('os')",
            "SUM([Sales]); open('/tmp/x', 'w')",
            "SUM([Sales]) / 0",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Bad", "expression": expression}],
                        self.rows,
                        self.headers,
                        "Sales data",
                    )

    def test_calculate_without_filters_keeps_the_current_context(self) -> None:
        values = evaluate_measures(
            [{
                "name": "Current sales",
                "expression": "CALCULATE(SUM([Sales]))",
            }],
            self.rows,
            self.headers,
            "Sales data",
        )
        self.assertEqual(values["Current sales"], Decimal("29.0"))

    def test_invalid_measure_dependency_and_non_numeric_values_report_clear_errors(self) -> None:
        with self.assertRaisesRegex(MeasureError, "cycle"):
            evaluate_measures([
                {"name": "A", "expression": "[B]"},
                {"name": "B", "expression": "[A]"},
            ], self.rows, self.headers)
        with self.assertRaisesRegex(MeasureError, "non-numeric"):
            evaluate_measures(
                [{"name": "Bad", "expression": "SUM([Note])"}],
                self.rows,
                self.headers,
            )

    def test_measure_list_requires_unique_names_and_known_definition_shape(self) -> None:
        with self.assertRaisesRegex(MeasureError, "duplicated"):
            validate_measures([
                {"name": "Sales", "expression": "SUM([Sales])"},
                {"name": "sales", "expression": "SUM([Sales])"},
            ])
        with self.assertRaises(MeasureError):
            validate_measures([{"name": "Sales", "expression": "SUM([Sales])", "code": "bad"}])

    def test_v4_projects_migrate_to_current_format_with_an_empty_measure_list(self) -> None:
        project = new_project("Legacy")
        project["format_version"] = 4
        project["model"].pop("measures")

        migrated = validate_project(project)

        self.assertEqual(FORMAT_VERSION, 68)
        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["model"]["measures"], [])

    def test_project_validation_checks_measure_definitions(self) -> None:
        project = new_project("Measures")
        project["model"]["measures"] = [{"name": "Sales", "expression": "SUM([Sales])"}]
        self.assertEqual(validate_project(project)["model"]["measures"], project["model"]["measures"])

        project["model"]["measures"] = [{"name": "Bad", "expression": "CALCULATE()"}]
        with self.assertRaises(ProjectFileError):
            validate_project(project)


if __name__ == "__main__":
    unittest.main()
