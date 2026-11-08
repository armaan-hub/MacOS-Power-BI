"""Tests for Task 36 info-empty-26 (42 empty/unavailable INFO functions)."""

import unittest
from decimal import Decimal

from analytics_studio.measures import evaluate_measures, MeasureError
from tools.dax_oracle_diff import local


class TestIteration126InfoEmpty26(unittest.TestCase):
    def test_part_a_countrows_blank_and_isempty(self):
        # Sample of Part A functions returning empty table
        self.assertEqual(local("COUNTROWS(INFO.ALTERNATEOFDEFINITIONS())"), "BLANK")
        self.assertEqual(local("IF(ISEMPTY(INFO.ALTERNATEOFDEFINITIONS()), \"e\", \"n\")"), "e")
        self.assertEqual(local("COUNTROWS(INFO.CALCULATIONGROUPS())"), "BLANK")
        self.assertEqual(local("IF(ISEMPTY(INFO.CALCULATIONGROUPS()), \"e\", \"n\")"), "e")
        self.assertEqual(local("COUNTROWS(INFO.HIERARCHIES())"), "BLANK")
        self.assertEqual(local("IF(ISEMPTY(INFO.HIERARCHIES()), \"e\", \"n\")"), "e")
        self.assertEqual(local("COUNTROWS(INFO.ROLES())"), "BLANK")
        self.assertEqual(local("IF(ISEMPTY(INFO.ROLES()), \"e\", \"n\")"), "e")

    def test_part_a_tocsv_headers(self):
        headers_alt = local('TOCSV(FILTER(INFO.ALTERNATEOFDEFINITIONS(), FALSE()), 3, ",", TRUE)')
        # live Power BI 2026-11-08: TOCSV ends with a newline even for an empty table
        self.assertEqual(headers_alt, "[ID],[ColumnID],[BaseColumnID],[BaseTableID],[Summarization]\n")

        headers_roles = local('TOCSV(FILTER(INFO.ROLES(), FALSE()), 3, ",", TRUE)')
        self.assertEqual(headers_roles, "[ID],[ModelID],[Name],[Description],[ModelPermission],[ModifiedTime]\n")

    def test_part_a_restriction_argument_validation(self):
        # Non-string argument errors with expected message
        res = local("COUNTROWS(INFO.ALTERNATEOFDEFINITIONS(1))")
        self.assertTrue(res.startswith("LOCAL-REJECT:The 'INFO.ALTERNATEOFDEFINITIONS' function expects a constant string representing a restriction name."))

        # String restriction argument is refused
        res_str = local('COUNTROWS(INFO.ALTERNATEOFDEFINITIONS("restriction"))')
        self.assertTrue(res_str.startswith("LOCAL-REJECT:'restriction' is not a valid restriction name."))

    def test_part_a_scalar_evaluation_error(self):
        res = local("INFO.ALTERNATEOFDEFINITIONS()")
        self.assertTrue(res.startswith("LOCAL-REJECT:The expression refers to multiple columns. Multiple columns cannot be converted to a scalar value."))

    def test_part_b_unavailable_functions(self):
        unavailable = [
            "INFO.CALENDARCOLUMNGROUPS",
            "INFO.CALENDARCOLUMNREFERENCES",
            "INFO.CALENDARS",
            "INFO.EXCLUDEDARTIFACTS",
            "INFO.USERDEFINEDFUNCTIONS",
        ]
        expected_msg = "The operation cannot be performed because it references an object or property that is unavailable in the current edition of the server or the compatibility level of the database."
        for fn in unavailable:
            res_count = local(f"COUNTROWS({fn}())")
            self.assertTrue(res_count.startswith("LOCAL-REJECT:") and expected_msg in res_count, f"{fn} COUNTROWS failed: {res_count}")
            res_scalar = local(f"{fn}()")
            self.assertTrue(res_scalar.startswith("LOCAL-REJECT:") and expected_msg in res_scalar, f"{fn} scalar failed: {res_scalar}")
            res_isempty = local(f'IF(ISEMPTY({fn}()), "e", "n")')
            self.assertTrue(res_isempty.startswith("LOCAL-REJECT:") and expected_msg in res_isempty, f"{fn} ISEMPTY failed: {res_isempty}")

    def test_calcdependency_and_dependencies_refused_with_measures(self):
        # In evaluate_measures with measures present, CALCDEPENDENCY and DEPENDENCIES are refused
        res1 = local("COUNTROWS(INFO.CALCDEPENDENCY())")
        self.assertTrue(res1.startswith("LOCAL-REJECT:INFO.CALCDEPENDENCY is not modelled by the local engine when the model holds measures."))
        res2 = local("COUNTROWS(INFO.DEPENDENCIES())")
        self.assertTrue(res2.startswith("LOCAL-REJECT:INFO.DEPENDENCIES is not modelled by the local engine when the model holds measures."))

    def test_info_function_in_calculate_filter_refused(self):
        # INFO functions in a CALCULATE filter predicate depend on external model table counts and are refused
        res = local("CALCULATE(COUNTROWS(Facts), Facts[Quantity] > COUNTROWS(INFO.ROLES()))")
        self.assertTrue(res.startswith("LOCAL-REJECT:INFO functions in a CALCULATE filter predicate depend on external model table counts and are not modelled."))

    def test_customised_model_refuses_info_functions(self):
        headers = ["Sales", "Quantity"]
        rows = [{"Sales": 10.0, "Quantity": 1}]
        table_context = [{
            "id": "facts",
            "name": "Facts",
            "headers": headers,
            "rows": rows,
            "column_types": {"Sales": "double", "Quantity": "int64"},
            "model_customised": ["calculated_columns"],
        }]
        with self.assertRaises(MeasureError) as ctx:
            evaluate_measures(
                [{"name": "m", "expression": "COUNTROWS(INFO.ROLES())"}],
                rows, headers, "Facts", measure_names=["m"],
                table_context=table_context, active_table_id="facts",
            )
        self.assertIn("INFO functions are not modelled", str(ctx.exception))


class InfoEmptyMeasuredTypeTests(unittest.TestCase):
    """Column types come from the measured table in the source, not from a guess on the column name."""

    TYPE_ERROR = "DAX comparison operations do not support comparing values of type"

    def test_text_column_compared_with_number_raises_the_type_error(self):
        # Power BI: MemberID is text, so the comparison with 1 is a type error even on an empty table
        res = local("COUNTROWS(FILTER(INFO.ROLEMEMBERSHIPS(),[MemberID]=1))")
        self.assertTrue(res.startswith("LOCAL-REJECT:") and self.TYPE_ERROR in res, res)

    def test_number_column_compared_with_text_raises_the_type_error(self):
        for expression in (
            'COUNTROWS(FILTER(INFO.DATASOURCES(),[MaxConnections]="x"))',
            'COUNTROWS(FILTER(INFO.EXPRESSIONS(),[Kind]="x"))',
            'COUNTROWS(FILTER(INFO.REFRESHPOLICIES(),[Mode]="x"))',
            'COUNTROWS(FILTER(INFO.RELATIONSHIPSTORAGES(),[Cardinality]="x"))',
        ):
            res = local(expression)
            self.assertTrue(res.startswith("LOCAL-REJECT:") and self.TYPE_ERROR in res, (expression, res))

    def test_matching_comparisons_stay_blank(self):
        self.assertEqual(local('COUNTROWS(FILTER(INFO.ROLEMEMBERSHIPS(),[MemberID]="x"))'), "BLANK")
        self.assertEqual(local("COUNTROWS(FILTER(INFO.DATASOURCES(),[Timeout]=1))"), "BLANK")
        self.assertEqual(local('COUNTROWS(FILTER(INFO.PARQUETFILESTORAGES(),[CreatedVersion]="x"))'), "BLANK")

    def test_relationships_state_is_text(self):
        res = local("COUNTROWS(FILTER(INFO.VIEW.RELATIONSHIPS(),[State]=1))")
        self.assertTrue(res.startswith("LOCAL-REJECT:") and self.TYPE_ERROR in res, res)
        self.assertEqual(local('COUNTROWS(FILTER(INFO.VIEW.RELATIONSHIPS(),[State]="x"))'), "BLANK")

    def test_same_error_as_an_ordinary_table_type_error(self):
        info = local("COUNTROWS(FILTER(INFO.ROLEMEMBERSHIPS(),[MemberID]=1))")
        plain = local("COUNTROWS(FILTER(INFO.ROLES(),[Name]=1))")
        self.assertEqual(info.split(":", 1)[0], plain.split(":", 1)[0])
        self.assertEqual(info, plain)

    def test_every_function_has_an_explicit_type_for_every_column(self):
        from analytics_studio import measures
        self.assertFalse(hasattr(measures, "_info_infer_type"))
        self.assertEqual(set(measures._INFO_EMPTY_COLUMN_TYPES), set(measures._INFO_EMPTY_TABLE_HEADERS))
        for fn, headers in measures._INFO_EMPTY_TABLE_HEADERS.items():
            self.assertEqual(list(measures._INFO_EMPTY_COLUMN_TYPES[fn]), headers, fn)
            self.assertLessEqual(set(measures._INFO_EMPTY_COLUMN_TYPES[fn].values()), {"text", "boolean", "int64", "datetime"})


class InfoEmptyRealAppTests(unittest.TestCase):
    """INFO.EXPRESSIONS and INFO.QUERYGROUPS in the real controller are refused when the project holds Power Query objects."""

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

    def test_plain_model_answers_the_empty_tables(self):
        controller = self.controller()
        self.assertTrue(controller.create_measure("E", "COUNTROWS(INFO.EXPRESSIONS())"))
        self.assertTrue(controller.create_measure("Q", "COUNTROWS(INFO.QUERYGROUPS())"))
        self.assertTrue(controller.create_measure("R", "COUNTROWS(INFO.ROLES())"))

    def test_query_parameter_refuses_expressions_and_querygroups(self):
        controller = self.controller()
        controller._project["query_parameters"] = [{"name": "Region", "type": "text", "current_value": "East"}]
        controller._refresh_report()  # the app refreshes the report (and its filter-context cache) after a project change
        self.assertFalse(controller.create_measure("E", "COUNTROWS(INFO.EXPRESSIONS())"))
        self.assertFalse(controller.create_measure("Q", "COUNTROWS(INFO.QUERYGROUPS())"))
        self.assertTrue(controller.create_measure("R", "COUNTROWS(INFO.ROLES())"))

    def test_query_group_refuses_expressions_and_querygroups(self):
        controller = self.controller()
        controller._project["data_sources"][0]["query_group"] = "Folder1"
        controller._refresh_report()
        self.assertFalse(controller.create_measure("E", "COUNTROWS(INFO.EXPRESSIONS())"))
        self.assertFalse(controller.create_measure("Q", "COUNTROWS(INFO.QUERYGROUPS())"))

    def test_query_with_load_off_refuses_expressions(self):
        controller = self.controller()
        extra = dict(controller._table_catalog[0])
        extra.update({"id": "extra", "sourceId": "extra-source", "name": "Hidden", "loadEnabled": False})
        controller._table_catalog.append(extra)
        controller._refresh_report()
        self.assertFalse(controller.create_measure("E", "COUNTROWS(INFO.EXPRESSIONS())"))

    def test_flag_in_table_context_for_engine(self):
        headers = ["Sales"]
        rows = [{"Sales": 10.0}]
        context = [{"id": "t", "name": "T", "headers": headers, "rows": rows,
                    "column_types": {"Sales": "double"}, "model_expressions": True}]
        for fn in ("INFO.EXPRESSIONS", "INFO.QUERYGROUPS"):
            with self.assertRaises(MeasureError) as ctx:
                evaluate_measures([{"name": "m", "expression": f"COUNTROWS({fn}())"}], rows, headers, "T",
                                  measure_names=["m"], table_context=context, active_table_id="t")
            self.assertIn("not modelled", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
