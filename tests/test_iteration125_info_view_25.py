"""Iteration 125 (Task 35): Tests for INFO.VIEW.* and INFO.* DAX functions."""

from __future__ import annotations

import unittest
from decimal import Decimal

from analytics_studio.measures import MeasureError, evaluate_measures


class InfoViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.headers = ["Sales", "Quantity", "Region", "Note"]
        self.rows = [
            {"Sales": Decimal("10.5"), "Quantity": Decimal("2"), "Region": "East", "Note": "Paid"},
            {"Sales": Decimal("20"), "Quantity": Decimal("3"), "Region": "West", "Note": ""},
            {"Sales": Decimal("-1.5"), "Quantity": Decimal("1"), "Region": "East", "Note": "Paid"},
            {"Sales": None, "Quantity": Decimal("4"), "Region": "North", "Note": "Late"},
            {"Sales": Decimal("0"), "Quantity": Decimal("0"), "Region": "West", "Note": "Paid"},
            {"Sales": Decimal("2.5"), "Quantity": Decimal("5"), "Region": "East", "Note": ""},
        ]
        self.table_context = [{
            "id": "facts",
            "name": "Facts",
            "headers": self.headers,
            "rows": self.rows,
            "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"},
        }]

    def evaluate(self, expr: str):
        return evaluate_measures(
            [{"name": "M", "expression": expr}],
            self.rows,
            self.headers,
            "Facts",
            measure_names=["M"],
            table_context=self.table_context,
            active_table_id="facts",
        )["M"]

    # --- Part A: INFO.VIEW.* ---

    def test_info_view_tables_count_and_columns(self) -> None:
        self.assertEqual(self.evaluate("COUNTROWS(INFO.VIEW.TABLES())"), Decimal("1"))
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.VIEW.TABLES(), [Name] & "", "|")'), "Facts")
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.VIEW.TABLES(), [DataCategory] & "", "|")'), "Regular")
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.VIEW.TABLES(), [StorageMode] & "", "|")'), "Import")
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.VIEW.TABLES(), [IsHidden] & "", "|")'), "FALSE")

    def test_info_view_columns_rows_and_types(self) -> None:
        self.assertEqual(self.evaluate("COUNTROWS(INFO.VIEW.COLUMNS())"), Decimal("5"))
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.VIEW.COLUMNS(), [Name] & "", "|")'),
            "RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61|Sales|Quantity|Region|Note",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.VIEW.COLUMNS(), [DataType] & "", "|")'),
            "Integer|Number|Integer|Text|Text",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.VIEW.COLUMNS(), [IsHidden] & "", "|")'),
            "TRUE|FALSE|FALSE|FALSE|FALSE",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.VIEW.COLUMNS(), [IsKey] & "", "|")'),
            "TRUE|FALSE|FALSE|FALSE|FALSE",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.VIEW.COLUMNS(), [IsNullable] & "", "|")'),
            "FALSE|TRUE|TRUE|TRUE|TRUE",
        )

    def test_info_view_measures_and_relationships_empty(self) -> None:
        # The measure being evaluated is itself a model measure, so the measures list is refused (see the Task 35 review tests)
        self.assertIsNone(self.evaluate("COUNTROWS(INFO.VIEW.RELATIONSHIPS())"))
        self.assertTrue(self.evaluate("ISEMPTY(INFO.VIEW.RELATIONSHIPS())"))

    def test_info_view_arity_and_scalar_errors(self) -> None:
        with self.assertRaises(MeasureError) as cm:
            self.evaluate("COUNTROWS(INFO.VIEW.TABLES(1))")
        self.assertIn("Too many arguments were passed to the INFO.VIEW.TABLES function", str(cm.exception))

        with self.assertRaises(MeasureError) as cm:
            self.evaluate("COUNTROWS(INFO.VIEW.COLUMNS('Facts'))")
        self.assertIn("Too many arguments were passed to the INFO.VIEW.COLUMNS function", str(cm.exception))

        with self.assertRaises(MeasureError) as cm:
            self.evaluate("INFO.VIEW.TABLES()")
        self.assertIn("Multiple columns cannot be converted to a scalar value", str(cm.exception))

    def test_info_view_columns_isempty_crash(self) -> None:
        with self.assertRaises(MeasureError) as cm:
            self.evaluate("ISEMPTY(INFO.VIEW.COLUMNS())")
        self.assertIn("xldc.cpp", str(cm.exception))

    def test_info_view_filter_context_ignored(self) -> None:
        self.assertEqual(
            self.evaluate('CALCULATE(COUNTROWS(INFO.VIEW.COLUMNS()), Facts[Region] = "East")'),
            Decimal("5"),
        )

    def test_info_view_unmodelled_field_refused(self) -> None:
        with self.assertRaises(MeasureError) as cm:
            self.evaluate('CONCATENATEX(INFO.VIEW.TABLES(), [ID] & "", "|")')
        self.assertIn("not modelled", str(cm.exception))

    # --- Part B: INFO.* ---

    def test_info_tables_count_and_columns(self) -> None:
        self.assertEqual(self.evaluate("COUNTROWS(INFO.TABLES())"), Decimal("1"))
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.TABLES(), [Name] & "", "|")'), "Facts")
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.TABLES(), [AlternateSourcePrecedence] & "", "|")'), "0")
        self.assertEqual(self.evaluate('CONCATENATEX(INFO.TABLES(), [IsHidden] & "", "|")'), "FALSE")

    def test_info_columns_explicit_types_and_alignment(self) -> None:
        self.assertEqual(self.evaluate("COUNTROWS(INFO.COLUMNS())"), Decimal("5"))
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.COLUMNS(), [ExplicitName] & "", "|")'),
            "RowNumber-2662979B-1795-4F74-8F37-6A1BA8059B61|Sales|Quantity|Region|Note",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.COLUMNS(), [ExplicitDataType] & "", "|")'),
            "6|8|6|2|2",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.COLUMNS(), [Alignment] & "", "|")'),
            "1|1|1|1|1",
        )
        self.assertEqual(
            self.evaluate('CONCATENATEX(INFO.COLUMNS(), [SummarizeBy] & "", "|")'),
            "1|1|1|1|1",
        )

    def test_info_measures_and_relationships_empty(self) -> None:
        self.assertIsNone(self.evaluate("COUNTROWS(INFO.RELATIONSHIPS())"))

    def test_info_restrictions_validation(self) -> None:
        with self.assertRaises(MeasureError) as cm:
            self.evaluate("COUNTROWS(INFO.TABLES(1))")
        self.assertIn("expects a constant string representing a restriction name", str(cm.exception))

        with self.assertRaises(MeasureError) as cm:
            self.evaluate('COUNTROWS(INFO.TABLES("a"))')
        self.assertIn("'a' is not a valid restriction name", str(cm.exception))

    def test_tocsv_header_only(self) -> None:
        csv = self.evaluate('TOCSV(FILTER(INFO.VIEW.TABLES(), FALSE()), 3, ",", TRUE)')
        self.assertTrue(csv.startswith("[ID],[Name],[Model]"))
        self.assertFalse(csv.endswith("\n"))


class InfoViewReviewFixTests(unittest.TestCase):
    """Task 35 review fixes: unmodelled-field rows, ISEMPTY over columns, model measures, customised models."""

    setUp = InfoViewTests.setUp
    evaluate = InfoViewTests.evaluate

    def refused(self, expr: str) -> str:
        with self.assertRaises(MeasureError) as cm:
            self.evaluate(expr)
        return str(cm.exception)

    def test_whole_row_comparison_of_unmodelled_fields_is_refused(self) -> None:
        for fn in ("INFO.VIEW.TABLES", "INFO.VIEW.COLUMNS", "INFO.TABLES", "INFO.COLUMNS"):
            for wrap in ("EXCEPT({0}(),{0}())", "INTERSECT({0}(),{0}())", "DISTINCT({0}())"):
                with self.subTest(fn=fn, wrap=wrap):
                    self.refused(f"COUNTROWS({wrap.format(fn)})")

    def test_contains_over_unmodelled_column_is_refused(self) -> None:
        self.refused('IF(CONTAINS(INFO.VIEW.TABLES(),[ID],1),1,0)')
        self.refused('IF(CONTAINSROW(INFO.VIEW.TABLES(),1),1,0)')

    def test_modelled_column_operations_still_work(self) -> None:
        self.assertEqual(self.evaluate("COUNTROWS(UNION(INFO.VIEW.TABLES(),INFO.VIEW.TABLES()))"), Decimal("2"))
        self.assertEqual(self.evaluate('COUNTROWS(CROSSJOIN(SELECTCOLUMNS(INFO.VIEW.TABLES(),"a",[Name]),SELECTCOLUMNS(INFO.VIEW.COLUMNS(),"b",[Name])))'), Decimal("5"))
        self.assertEqual(self.evaluate('COUNTROWS(FILTER(INFO.VIEW.COLUMNS(),[Name]="Sales"))'), Decimal("1"))
        self.assertEqual(self.evaluate('COUNTROWS(EXCEPT(SELECTCOLUMNS(INFO.VIEW.COLUMNS(),"n",[Name]),SELECTCOLUMNS(INFO.VIEW.COLUMNS(),"n",[Name])))'), None)

    def test_isempty_info_columns_matches_info_view_columns(self) -> None:
        for fn in ("INFO.VIEW.COLUMNS", "INFO.COLUMNS"):
            for expr in (
                f"ISEMPTY({fn}())",
                f'IF(ISEMPTY({fn}()),"e","n")',
                f'IF(NOT(ISEMPTY({fn}())),"n","e")',
                f'VAR t = {fn}() RETURN IF(ISEMPTY(t),"e","n")',
            ):
                with self.subTest(expr=expr):
                    self.assertIn("xldc.cpp", self.refused(expr))

    def test_isempty_other_info_tables_unchanged(self) -> None:
        self.assertEqual(self.evaluate('IF(ISEMPTY(INFO.VIEW.TABLES()),"e","n")'), "n")
        self.assertEqual(self.evaluate('IF(ISEMPTY(INFO.TABLES()),"e","n")'), "n")
        self.assertEqual(self.evaluate('IF(ISEMPTY(INFO.RELATIONSHIPS()),"e","n")'), "e")

    def test_info_measures_refused_when_the_model_holds_measures(self) -> None:
        for fn in ("INFO.VIEW.MEASURES", "INFO.MEASURES"):
            for expr in (f"COUNTROWS({fn}())", f"ISEMPTY({fn}())", f"COUNTROWS(FILTER({fn}(),TRUE()))"):
                with self.subTest(expr=expr):
                    self.assertIn("not modelled", self.refused(expr))

    def test_customised_model_refuses_info_functions(self) -> None:
        for setting in ("calculated_columns", "key_column"):
            context = [dict(self.table_context[0], model_customised=[setting])]
            with self.subTest(setting=setting), self.assertRaises(MeasureError):
                evaluate_measures(
                    [{"name": "M", "expression": "COUNTROWS(INFO.VIEW.COLUMNS())"}], self.rows, self.headers, "Facts",
                    measure_names=["M"], table_context=context, active_table_id="facts",
                )
        context = [dict(self.table_context[0], date_column="Sales")]
        with self.assertRaises(MeasureError):
            evaluate_measures(
                [{"name": "M", "expression": "COUNTROWS(INFO.TABLES())"}], self.rows, self.headers, "Facts",
                measure_names=["M"], table_context=context, active_table_id="facts",
            )


class InfoViewRealAppTests(unittest.TestCase):
    """The measure path of the real controller: every expression there is a model measure."""

    @classmethod
    def setUpClass(cls) -> None:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def controller(self):
        import tempfile
        from pathlib import Path
        from PySide6.QtCore import QSettings
        from analytics_studio.controller import StudioController
        from analytics_studio.inline_data import parse_pasted_table
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        settings = QSettings(str(Path(self.temp_dir.name) / "settings.ini"), QSettings.Format.IniFormat)
        controller = StudioController(self.app, settings)
        data = parse_pasted_table("Region,Sales\nEast,10\nWest,20\nEast,5", name="T")
        self.assertTrue(controller._commit_inline(data))
        return controller

    def test_measures_info_is_refused_in_the_app(self) -> None:
        controller = self.controller()
        self.assertFalse(controller.create_measure("Count", "COUNTROWS(INFO.VIEW.MEASURES())"))
        self.assertFalse(controller.create_measure("Count2", "COUNTROWS(INFO.MEASURES())"))

    def test_other_info_function_is_allowed_in_a_plain_app_model(self) -> None:
        controller = self.controller()
        self.assertTrue(controller.create_measure("Tables", "COUNTROWS(INFO.VIEW.TABLES())"))
        self.assertFalse(controller.create_measure("Count", "COUNTROWS(INFO.VIEW.MEASURES())"))

    def test_calculated_column_makes_the_app_refuse_info_columns(self) -> None:
        controller = self.controller()
        self.assertEqual(controller.save_calculated_column("Double", "[Sales] * 2"), "")
        self.assertFalse(controller.create_measure("Cols", "COUNTROWS(INFO.VIEW.COLUMNS())"))
        self.assertFalse(controller.create_measure("Tabs", "COUNTROWS(INFO.TABLES())"))


if __name__ == "__main__":
    unittest.main()
