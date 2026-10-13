"""Safe reusable Power Query scalar function definitions and invocation."""

from __future__ import annotations

import unittest
import os
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import (
    ManageQueryFunctionsDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import (
    PowerQueryMScriptError,
    m_script_matches_steps,
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.project import FORMAT_VERSION, ProjectFileError, new_project, validate_project
from analytics_studio.query_parameters import parameter_values
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    column_types_after_steps,
)

from analytics_studio.query_functions import (
    QueryFunctionError,
    coerce_function_argument,
    query_function_to_m,
    validate_function_result,
    validate_query_functions,
    validate_typed_scalar,
)


class QueryFunctionDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Power Query function tests"])

    def setUp(self) -> None:
        self.source = ImportCandidate(
            "csv",
            ["Name", "Amount"],
            [{"Name": " ada ", "Amount": "1.25"}, {"Name": "BOB", "Amount": "4"}],
            {},
            [],
        )
        self.functions = [
            {
                "name": "NormalizeName",
                "parameter": "Value",
                "parameter_type": "text",
                "return_type": "text",
                "expression": "Text.Upper(Text.Trim(Value))",
            },
            {
                "name": "DoubleAmount",
                "parameter": "Value",
                "parameter_type": "decimal_number",
                "return_type": "decimal_number",
                "expression": "Value * 2",
            },
        ]

    def test_validates_typed_function_and_safe_body(self) -> None:
        functions = validate_query_functions([{
            "name": "NormalizeName",
            "parameter": "Value",
            "parameter_type": "text",
            "return_type": "text",
            "expression": "Text.Upper(Text.Trim(Value))",
        }])

        self.assertEqual(functions, [{
            "name": "NormalizeName",
            "parameter": "Value",
            "parameter_type": "text",
            "return_type": "text",
            "expression": "Text.Upper(Text.Trim(Value))",
        }])

    def test_rejects_python_and_row_scoped_function_bodies(self) -> None:
        for expression in ("__import__(\"os\")", "Text.Upper([Name])"):
            with self.subTest(expression=expression):
                with self.assertRaises(QueryFunctionError):
                    validate_query_functions([{
                        "name": "Unsafe",
                        "parameter": "Value",
                        "parameter_type": "text",
                        "return_type": "text",
                        "expression": expression,
                    }])

    def test_rejects_function_and_parameter_names_that_shadow_m_namespaces(self) -> None:
        for changes in (
            {"name": "Text"},
            {"name": "Table"},
            {"parameter": "Number"},
            {"parameter": "Date"},
        ):
            with self.subTest(changes=changes):
                definition = {
                    "name": "NormalizeName",
                    "parameter": "Value",
                    "parameter_type": "text",
                    "return_type": "text",
                    **changes,
                }
                definition["expression"] = (
                    f"Text.Upper({definition['parameter']})"
                )
                with self.assertRaisesRegex(QueryFunctionError, "namespace"):
                    validate_query_functions([definition])

    def test_function_result_types_are_checked_without_text_coercion(self) -> None:
        for return_type, expression in (
            ("whole_number", '"42"'),
            ("decimal_number", '"4.2"'),
            ("boolean", '"true"'),
            ("date", '"2026-01-15"'),
            ("datetime", '"2026-01-15T12:30:00"'),
        ):
            with self.subTest(return_type=return_type):
                with self.assertRaisesRegex(QueryFunctionError, "function result"):
                    validate_query_functions([{
                        "name": "TypedResult",
                        "parameter": "Value",
                        "parameter_type": "text",
                        "return_type": return_type,
                        "expression": expression,
                    }])

    def test_whole_number_functions_enforce_signed_int64_range(self) -> None:
        minimum = Decimal(-(1 << 63))
        maximum = Decimal((1 << 63) - 1)
        for value in (minimum, maximum):
            self.assertEqual(coerce_function_argument("whole_number", value), value)
            self.assertEqual(validate_function_result("whole_number", value), value)
            self.assertEqual(validate_typed_scalar("whole_number", value), value)
        for value in (minimum - 1, maximum + 1):
            with self.subTest(value=value):
                for validate in (
                    lambda: coerce_function_argument("whole_number", value),
                    lambda: validate_function_result("whole_number", value),
                    lambda: validate_typed_scalar("whole_number", value),
                ):
                    with self.assertRaises(QueryFunctionError):
                        validate()

    def test_custom_columns_execute_functions_and_preserve_declared_result_types(self) -> None:
        steps = [
            {
                "op": "add_custom_column",
                "name": "Normalized",
                "expression": "NormalizeName([Name])",
            },
            {
                "op": "add_custom_column",
                "name": "Doubled",
                "expression": "DoubleAmount(Number.From([Amount]))",
                "output_type": "decimal_number",
            },
        ]
        result = apply_transformations(
            self.source,
            steps,
            parameters=parameter_values([], self.functions),
        )

        self.assertEqual(
            [row["Normalized"] for row in result.rows], ["ADA", "BOB"]
        )
        self.assertEqual([row["Doubled"] for row in result.rows], [Decimal("2.50"), Decimal("8")])
        self.assertEqual(
            column_types_after_steps(
                self.source.headers, steps, output_headers=result.headers
            )["Doubled"],
            "decimal_number",
        )

    def test_advanced_editor_round_trips_typed_functions_after_source(self) -> None:
        steps = [
            {
                "op": "add_custom_column",
                "name": "Normalized",
                "expression": "NormalizeName([Name])",
            },
            {
                "op": "add_custom_column",
                "name": "Doubled",
                "expression": "DoubleAmount(Number.From([Amount]))",
                "output_type": "decimal_number",
            },
        ]
        script = steps_to_m_script(
            steps, "Sales", query_functions=self.functions
        )
        lines = script.splitlines()
        self.assertIn('Source = #"Sales"', lines[1])
        self.assertIn(
            "NormalizeName = (Value as nullable text) as nullable text =>", lines[2]
        )
        self.assertIn('#"Step 1" = Table.AddColumn', lines[4])
        self.assertIn("each DoubleAmount(Number.From([Amount])), type number)", lines[5])
        parsed = parse_m_script(
            script, "Sales", query_functions=self.functions
        )
        self.assertEqual(parsed, steps)
        self.assertTrue(m_script_matches_steps(
            script, "Sales", steps, query_functions=self.functions
        ))
        self.assertEqual(
            apply_transformations(
                self.source, parsed,
                parameters=parameter_values([], self.functions),
            ),
            apply_transformations(
                self.source, steps,
                parameters=parameter_values([], self.functions),
            ),
        )
        changed_definition = script.replace(
            "Text.Upper(Text.Trim(Value))", "Text.Lower(Text.Trim(Value))"
        )
        with self.assertRaises(PowerQueryMScriptError):
            parse_m_script(
                changed_definition, "Sales", query_functions=self.functions
            )

    def test_nullable_function_signature_round_trips_null_values(self) -> None:
        self.assertIn(
            "(Value as nullable text) as nullable text",
            query_function_to_m(self.functions[0]),
        )
        steps = [{
            "op": "add_custom_column",
            "name": "MaybeName",
            "expression": "NormalizeName(null)",
        }]
        script = steps_to_m_script(
            steps, "Sales", query_functions=self.functions
        )
        parsed = parse_m_script(
            script, "Sales", query_functions=self.functions
        )
        result = apply_transformations(
            self.source, parsed,
            parameters=parameter_values([], self.functions),
        )
        self.assertEqual([row["MaybeName"] for row in result.rows], [None, None])

    def test_custom_column_rejects_a_false_output_type(self) -> None:
        with self.assertRaisesRegex(TransformationError, "whole number"):
            apply_transformations(
                self.source,
                [{
                    "op": "add_custom_column",
                    "name": "Wrong",
                    "expression": '"not a number"',
                    "output_type": "whole_number",
                }],
            )

    def test_project_migration_persists_and_validates_function_registry(self) -> None:
        old = new_project("v77")
        old["format_version"] = 77
        old.pop("query_functions")
        migrated = validate_project(old)
        self.assertEqual(migrated["format_version"], 78)
        self.assertEqual(migrated["query_functions"], [])
        self.assertEqual(FORMAT_VERSION, 78)

        project = new_project("functions")
        project["query_functions"] = self.functions
        project["data_sources"] = [{
            "id": "sales", "name": "Sales", "kind": "inline",
            "headers": ["Name", "Amount"],
            "rows": [{"Name": "Ada", "Amount": "1.25"}],
            "transform_steps": [{
                "op": "add_custom_column",
                "name": "Normalized",
                "expression": "NormalizeName([Name])",
            }],
        }]
        saved = validate_project(project)
        self.assertEqual(saved["query_functions"], self.functions)
        project["query_functions"] = self.functions[1:]
        with self.assertRaisesRegex(ProjectFileError, "Unsupported name or function"):
            validate_project(project)

    def test_manage_functions_and_custom_column_ribbon_are_available(self) -> None:
        dialog = TransformDataDialog(
            self.source, query_name="Sales", query_functions=self.functions
        )
        self.assertIsNotNone(dialog.findChild(
            QToolButton, "managePowerQueryFunctionsButton"
        ))
        dialog._set_combo_data(dialog.operation_combo, "add_custom_column")
        dialog._configure_editor()
        dialog._set_combo_data(dialog.custom_function_combo, "NormalizeName")
        dialog._insert_custom_function()
        self.assertEqual(
            dialog.custom_expression_edit.toPlainText(), "NormalizeName([Column])"
        )
        dialog._set_combo_data(dialog.custom_output_type_combo, "decimal_number")
        dialog.value_edit.setText("Doubled")
        self.assertEqual(dialog._create_step(), {
            "op": "add_custom_column",
            "name": "Doubled",
            "expression": "NormalizeName([Column])",
            "output_type": "decimal_number",
        })
        dialog.deleteLater()

    def test_unavailable_query_blocks_changes_to_a_function_it_uses(self) -> None:
        unavailable_candidate = ImportCandidate("query", [], [], {}, [])
        dialog = TransformDataDialog(
            self.source,
            query_name="Sales",
            queries=[
                {
                    "id": "active", "name": "Sales", "candidate": self.source,
                    "steps": [],
                },
                {
                    "id": "unavailable", "name": "Remote Sales",
                    "candidate": unavailable_candidate, "source_candidate": None,
                    "steps": [{
                        "op": "add_custom_column",
                        "name": "Normalized",
                        "expression": "NormalizeName([Name])",
                    }],
                    "is_unavailable": True,
                },
            ],
            active_query_id="active",
            query_functions=self.functions,
        )

        def accept_manager(manager: ManageQueryFunctionsDialog) -> QDialog.DialogCode:
            manager._functions[0]["expression"] = "Text.Lower(Text.Trim(Value))"
            manager._accept_functions()
            return QDialog.DialogCode.Accepted

        with patch.object(ManageQueryFunctionsDialog, "exec", new=accept_manager):
            dialog._manage_query_functions()
        self.assertEqual(dialog._query_functions, self.functions)
        self.assertIn("unavailable query", dialog.error_label.text())
        self.assertEqual(
            dialog._query_states["unavailable"]["steps"][0]["expression"],
            "NormalizeName([Name])",
        )
        dialog.deleteLater()

    def test_function_edits_recalculate_query_and_reference_outputs_on_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sales.csv"
            path.write_text("Amount\n10\n20\n", encoding="utf-8")
            controller = StudioController(
                self.app,
                QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
            )
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            root_id = str(controller.activeTableId)
            functions = [{
                "name": "DoubleAmount",
                "parameter": "Value",
                "parameter_type": "decimal_number",
                "return_type": "decimal_number",
                "expression": "Value * 2",
            }]
            controller._project["query_functions"] = functions
            steps = [{
                "op": "add_custom_column",
                "name": "Doubled",
                "expression": "DoubleAmount(Number.From([Amount]))",
                "output_type": "decimal_number",
            }]
            raw = controller._raw_candidate_for_source(
                next(item for item in controller._project["data_sources"] if item["id"] == root_id)
            )
            preview = apply_transformations(
                raw, steps, parameters=parameter_values([], functions)
            )
            self.assertTrue(controller._commit_transform_steps(
                root_id, steps, preview, previewed_source=raw,
            ), controller.statusMessage)
            reference_candidate = controller._loaded_candidates[root_id]
            self.assertTrue(controller._create_saved_query(
                "Sales reference", [root_id], reference_candidate,
                {"operation": "reference", "source_ids": [root_id]},
                {"Amount": "text", "Doubled": "decimal_number"},
            ), controller.statusMessage)
            reference_id = str(controller._active_source_id)
            self.assertTrue(controller._create_saved_query(
                "Sales excluded", [root_id], reference_candidate,
                {"operation": "reference", "source_ids": [root_id]},
                {"Amount": "text", "Doubled": "decimal_number"},
            ), controller.statusMessage)
            excluded_id = str(controller._active_source_id)
            self.assertTrue(controller._create_saved_query(
                "Sales excluded reference", [root_id], reference_candidate,
                {"operation": "reference", "source_ids": [root_id]},
                {"Amount": "text", "Doubled": "decimal_number"},
            ), controller.statusMessage)
            excluded_reference_id = str(controller._active_source_id)
            excluded_reference_source = next(
                item for item in controller._project["data_sources"]
                if item["id"] == excluded_reference_id
            )
            excluded_reference_source["include_in_report_refresh"] = False
            excluded_source = next(
                item for item in controller._project["data_sources"]
                if item["id"] == excluded_id
            )
            excluded_raw = controller._raw_candidate_for_source(excluded_source)
            excluded_steps = [{
                "op": "add_custom_column",
                "name": "Recomputed",
                "expression": "DoubleAmount(Number.From([Amount]))",
                "output_type": "decimal_number",
            }]
            excluded_preview = apply_transformations(
                excluded_raw, excluded_steps,
                parameters=parameter_values([], functions),
            )
            self.assertTrue(controller._commit_transform_steps(
                excluded_id, excluded_steps, excluded_preview,
                previewed_source=excluded_raw,
            ), controller.statusMessage)
            excluded_source = next(
                item for item in controller._project["data_sources"]
                if item["id"] == excluded_id
            )
            excluded_source["include_in_report_refresh"] = False
            self.assertTrue(controller.selectTable(root_id), controller.statusMessage)

            def accept_manager(manager: ManageQueryFunctionsDialog) -> QDialog.DialogCode:
                manager._functions[0]["expression"] = "Value * 3"
                manager._accept_functions()
                return QDialog.DialogCode.Accepted

            def accept_editor(dialog: TransformDataDialog) -> QDialog.DialogCode:
                with patch.object(ManageQueryFunctionsDialog, "exec", new=accept_manager):
                    dialog._manage_query_functions()
                dialog._switch_query(dialog._query_order.index(reference_id))
                dialog._refresh_source_preview()
                self.assertEqual(
                    [
                        row["Doubled"]
                        for row in dialog._query_states[root_id]["preview_candidate"].rows
                    ],
                    [Decimal("30"), Decimal("60")],
                )
                self.assertEqual(
                    [
                        row["Doubled"]
                        for row in dialog._query_states[excluded_reference_id][
                            "preview_candidate"
                        ].rows
                    ],
                    [Decimal("30"), Decimal("60")],
                )
                dialog._switch_query(dialog._query_order.index(root_id))
                for query_id in dialog._query_order:
                    query = dialog._query_states[query_id]
                    replay = apply_transformations(
                        query["source_candidate"], query["steps"],
                        parameters=dialog._parameter_values(),
                    )
                    if replay != query["preview_candidate"]:
                        raise AssertionError(
                            f"stale {query['name']}: replay={replay!r}, "
                            f"preview={query['preview_candidate']!r}"
                        )
                dialog._accept_candidate()
                return QDialog.DialogCode.Accepted

            with (
                patch.object(TransformDataDialog, "exec", new=accept_editor),
                patch("analytics_studio.local_table_dialogs.QMessageBox.warning") as warning,
            ):
                applied = controller.transform_data_dialog()
            self.assertTrue(applied, f"{controller.statusMessage}; {warning.call_args}")

            self.assertEqual(
                [row["Doubled"] for row in controller._loaded_candidates[root_id].rows],
                [Decimal("30"), Decimal("60")],
            )
            self.assertEqual(
                [row["Doubled"] for row in controller._loaded_candidates[reference_id].rows],
                [Decimal("30"), Decimal("60")],
            )
            self.assertEqual(
                [row["Recomputed"] for row in controller._loaded_candidates[excluded_id].rows],
                [Decimal("30"), Decimal("60")],
            )
            self.assertEqual(
                [
                    row["Doubled"]
                    for row in controller._loaded_candidates[excluded_reference_id].rows
                ],
                [Decimal("30"), Decimal("60")],
            )
            self.assertEqual(
                controller._project["query_functions"][0]["expression"], "Value * 3"
            )

            project_path = root / "functions.npa"
            self.assertTrue(controller._save_to(project_path), controller.statusMessage)
            reopened = StudioController(
                self.app,
                QSettings(str(root / "reopened-settings.ini"), QSettings.Format.IniFormat),
            )
            self.assertTrue(reopened.open_project_path(project_path), reopened.statusMessage)
            self.assertEqual(reopened._project["format_version"], 78)
            self.assertEqual(reopened._project["query_functions"][0]["expression"], "Value * 3")
            for query_id, column in (
                (root_id, "Doubled"),
                (reference_id, "Doubled"),
                (excluded_id, "Recomputed"),
                (excluded_reference_id, "Doubled"),
            ):
                self.assertEqual(
                    [row[column] for row in reopened._loaded_candidates[query_id].rows],
                    [Decimal("30"), Decimal("60")],
                )
            reopened.refresh_all_sources()
            for query_id, column in (
                (root_id, "Doubled"),
                (reference_id, "Doubled"),
                (excluded_id, "Recomputed"),
                (excluded_reference_id, "Doubled"),
            ):
                self.assertEqual(
                    [row[column] for row in reopened._loaded_candidates[query_id].rows],
                    [Decimal("30"), Decimal("60")],
                )


if __name__ == "__main__":
    unittest.main()
