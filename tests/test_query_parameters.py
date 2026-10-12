"""Power Query parameter validation, M, project, and refresh acceptance."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import (
    ManageQueryParametersDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import (
    PowerQueryMScriptError,
    m_compatibility_issues,
    m_script_matches_steps,
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.project import (
    FORMAT_VERSION,
    ProjectFileError,
    new_project,
    validate_project,
)
from analytics_studio.query_parameters import (
    QueryParameterError,
    normalize_query_parameter,
    parameter_values,
)
from analytics_studio.transformations import TransformationError, apply_transformations


class QueryParameterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Power Query parameter tests"])

    def setUp(self) -> None:
        self.source = ImportCandidate(
            "csv", ["Amount", "Region"],
            [
                {"Amount": "10", "Region": "East"},
                {"Amount": "20", "Region": "West"},
                {"Amount": "30", "Region": "East"},
            ], {}, [],
        )
        self.numeric_filter = {
            "op": "filter_rows", "column": "Amount",
            "operator": "greater_than", "parameter": "MinimumAmount",
        }

    def test_parameter_values_are_typed_and_canonicalized(self) -> None:
        self.assertEqual(normalize_query_parameter({
            "name": "MinimumAmount", "type": "decimal_number",
            "current_value": "0015.00",
        }), {
            "name": "MinimumAmount", "type": "decimal_number",
            "current_value": "15.00",
        })
        self.assertEqual(normalize_query_parameter({
            "name": "StartDate", "type": "date", "current_value": "2026-08-01",
        })["current_value"], "2026-08-01")
        for name, type_name, value in (
            ("1bad", "text", "x"), ("let", "text", "x"),
            ("Limit", "whole_number", "1.5"),
            ("Enabled", "boolean", "yes"),
            ("StartDate", "date", "08/01/2026"),
        ):
            with self.subTest(name=name, type=type_name, value=value):
                with self.assertRaises(QueryParameterError):
                    normalize_query_parameter({
                        "name": name, "type": type_name, "current_value": value,
                    })

    def test_parameterized_steps_resolve_current_value_at_evaluation_time(self) -> None:
        first = apply_transformations(
            self.source, [self.numeric_filter],
            parameters={"MinimumAmount": "15"},
        )
        second = apply_transformations(
            self.source, [self.numeric_filter],
            parameters={"MinimumAmount": "25"},
        )
        self.assertEqual([row["Amount"] for row in first.rows], ["20", "30"])
        self.assertEqual([row["Amount"] for row in second.rows], ["30"])
        with self.assertRaisesRegex(TransformationError, "no current value"):
            apply_transformations(self.source, [self.numeric_filter])

    def test_advanced_editor_round_trips_parameter_references_without_baking_values(self) -> None:
        parameters = {"MinimumAmount": "15", "WestRegion": "West"}
        steps = [{
            "op": "filter_rows_advanced",
            "clauses": [
                {
                    "column": "Amount", "operator": "greater_than",
                    "parameter": "MinimumAmount", "join": "and",
                },
                {
                    "column": "Region", "operator": "equals",
                    "parameter": "WestRegion", "join": "or",
                },
            ],
        }]
        script = steps_to_m_script(steps, "Sales")
        self.assertIn("MinimumAmount", script)
        self.assertIn("WestRegion", script)
        parsed = parse_m_script(
            script, "Sales", parameter_names=set(parameters)
        )
        self.assertEqual(parsed, steps)
        self.assertTrue(m_script_matches_steps(
            script, "Sales", steps, parameter_names=set(parameters)
        ))
        self.assertEqual(m_compatibility_issues(
            steps, parameter_names=set(parameters)
        ), [])
        self.assertEqual(
            [row["Amount"] for row in apply_transformations(
                self.source, parsed, parameters=parameters
            ).rows],
            ["20", "30"],
        )
        self.assertEqual(
            [row["Amount"] for row in apply_transformations(
                self.source, parsed,
                parameters={"MinimumAmount": "25", "WestRegion": "North"},
            ).rows],
            ["30"],
        )

    def test_m_script_rejects_unknown_parameter_names(self) -> None:
        script = steps_to_m_script([self.numeric_filter], "Sales")
        with self.assertRaises(PowerQueryMScriptError):
            parse_m_script(script, "Sales")

    def test_project_v75_migration_adds_parameters_and_rejects_dangling_references(self) -> None:
        old = new_project("v75 project")
        old["format_version"] = 75
        old.pop("query_parameters")
        migrated = validate_project(old)
        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["query_parameters"], [])

        project = new_project("parameterized source")
        project["query_parameters"] = [{
            "name": "MinimumAmount", "type": "whole_number", "current_value": "15",
        }]
        project["data_sources"] = [{
            "id": "sales", "name": "Sales", "kind": "inline",
            "headers": ["Amount"], "rows": [{"Amount": "20"}],
            "transform_steps": [self.numeric_filter],
        }]
        self.assertEqual(
            validate_project(project)["query_parameters"][0]["current_value"], "15"
        )
        project["query_parameters"] = []
        with self.assertRaisesRegex(ProjectFileError, "missing Power Query parameter"):
            validate_project(project)

    def test_power_query_home_ribbon_exposes_parameter_manager(self) -> None:
        dialog = TransformDataDialog(
            self.source, query_name="Sales",
            query_parameters=[{
                "name": "MinimumAmount", "type": "whole_number",
                "current_value": "15",
            }],
        )
        self.assertIsNotNone(dialog.findChild(
            QToolButton, "managePowerQueryParametersButton"
        ))
        dialog.deleteLater()

    def test_filter_controls_save_parameter_references_for_simple_and_advanced_filters(self) -> None:
        parameters = [
            {
                "name": "MinimumAmount", "type": "whole_number",
                "current_value": "15",
            },
            {
                "name": "WestRegion", "type": "text",
                "current_value": "West",
            },
        ]
        dialog = TransformDataDialog(
            self.source, query_name="Sales", query_parameters=parameters,
        )

        dialog._set_combo_data(dialog.operation_combo, "filter_rows")
        dialog._configure_editor()
        dialog._set_combo_text(dialog.column_combo, "Amount")
        dialog._set_combo_data(dialog.option_combo, "greater_than")
        dialog._set_combo_data(dialog.filter_parameter_combo, "MinimumAmount")
        simple_step = dialog._create_step()
        self.assertEqual(simple_step, self.numeric_filter)
        self.assertEqual(
            [row["Amount"] for row in apply_transformations(
                self.source, [simple_step], parameters={"MinimumAmount": "15"}
            ).rows],
            ["20", "30"],
        )

        dialog._set_combo_data(dialog.operation_combo, "filter_rows_advanced")
        dialog._configure_editor()
        dialog._set_combo_text(dialog.column_combo, "Region")
        dialog._set_combo_data(dialog.option_combo, "equals")
        dialog._set_combo_data(dialog.filter_parameter_combo, "WestRegion")
        clause = dialog._current_advanced_filter_clause(index=0)
        self.assertEqual(clause, {
            "column": "Region", "operator": "equals",
            "parameter": "WestRegion", "join": "and",
        })
        dialog._filter_clauses = [clause]
        dialog._render_advanced_filter_clauses(select_row=0)
        self.assertEqual(
            dialog._create_step(),
            {"op": "filter_rows_advanced", "clauses": [clause]},
        )
        self.assertIn("WestRegion", dialog.advanced_filter_clause_list.item(0).text())
        self.assertEqual(
            [row["Region"] for row in apply_transformations(
                self.source, [dialog._create_step()], parameters={"WestRegion": "West"}
            ).rows],
            ["West"],
        )
        dialog.deleteLater()

    def test_typed_parameter_drives_custom_column_and_round_trips_through_m(self) -> None:
        definitions = [
            {
                "name": "ScaleFactor", "type": "decimal_number",
                "current_value": "2.5",
            },
            {
                "name": "CurrencyLabel", "type": "text",
                "current_value": " AED",
            },
        ]
        parameters = parameter_values(definitions)
        step = {
            "op": "add_custom_column",
            "name": "Scaled amount",
            "expression": "Number.From([Amount]) * ScaleFactor & CurrencyLabel",
        }
        first = apply_transformations(self.source, [step], parameters=parameters)
        self.assertEqual(
            [row["Scaled amount"] for row in first.rows],
            ["25 AED", "50 AED", "75 AED"],
        )

        changed_parameters = parameter_values([
            {**definitions[0], "current_value": "4"}, definitions[1],
        ])
        changed = apply_transformations(
            self.source, [step], parameters=changed_parameters
        )
        self.assertEqual(
            [row["Scaled amount"] for row in changed.rows],
            ["40 AED", "80 AED", "120 AED"],
        )

        names = set(parameters)
        script = steps_to_m_script([step], "Sales", parameter_names=names)
        self.assertIn("ScaleFactor", script)
        parsed = parse_m_script(script, "Sales", parameter_names=names)
        self.assertEqual(parsed, [step])
        self.assertEqual(m_compatibility_issues([step], parameter_names=names), [])
        self.assertEqual(
            apply_transformations(self.source, parsed, parameters=parameters).rows,
            first.rows,
        )

    def test_custom_column_editor_can_insert_a_saved_parameter(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            query_name="Sales",
            query_parameters=[{
                "name": "ScaleFactor", "type": "decimal_number",
                "current_value": "2.5",
            }],
        )
        dialog._set_combo_data(dialog.operation_combo, "add_custom_column")
        dialog._configure_editor()
        dialog._set_combo_data(dialog.custom_parameter_combo, "ScaleFactor")
        dialog.insert_custom_parameter_button.click()
        self.assertEqual(dialog.custom_expression_edit.toPlainText(), "ScaleFactor")
        dialog.custom_expression_edit.setPlainText(
            "Number.From([Amount]) * ScaleFactor & CurrencyLabel"
        )
        self.assertEqual(
            dialog._create_step()["expression"],
            "Number.From([Amount]) * ScaleFactor & CurrencyLabel",
        )
        dialog.deleteLater()

    def test_boolean_date_and_datetime_parameters_are_typed_in_formulas(self) -> None:
        parameters = parameter_values([
            {"name": "Enabled", "type": "boolean", "current_value": "true"},
            {"name": "StartDate", "type": "date", "current_value": "2026-08-01"},
            {
                "name": "AsOfDate", "type": "datetime",
                "current_value": "2026-08-02T10:30:00Z",
            },
        ])
        steps = [
            {
                "op": "add_custom_column", "name": "Status",
                "expression": 'if Enabled then "On" else "Off"',
            },
            {
                "op": "add_custom_column", "name": "Start year",
                "expression": "Date.Year(StartDate)",
            },
            {
                "op": "add_custom_column", "name": "Refresh year",
                "expression": "Date.Year(AsOfDate)",
            },
        ]
        transformed = apply_transformations(self.source, steps, parameters=parameters)
        self.assertEqual(
            [(row["Status"], row["Start year"], row["Refresh year"])
             for row in transformed.rows],
            [("On", "2026", "2026")] * 3,
        )

    def test_parameterized_custom_column_replays_after_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sales.csv"
            path.write_text(
                "Amount,Region\n10,East\n20,West\n30,East\n", encoding="utf-8"
            )
            app = QApplication.instance() or self.app
            controller = StudioController(
                app, QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            )
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_id = controller.activeTableId
            controller._project["query_parameters"] = [{
                "name": "ScaleFactor", "type": "whole_number",
                "current_value": "2",
            }]
            steps = [{
                "op": "add_custom_column",
                "name": "Scaled amount",
                "expression": "Number.From([Amount]) * ScaleFactor",
            }]
            raw = controller._raw_candidate_for_source(
                next(
                    item for item in controller._project["data_sources"]
                    if item["id"] == source_id
                )
            )
            preview = apply_transformations(
                raw, steps,
                parameters=parameter_values(controller._project["query_parameters"]),
            )
            self.assertTrue(controller._commit_transform_steps(
                source_id, steps, preview, previewed_source=raw,
            ), controller.statusMessage)
            self.assertEqual(
                [row["Scaled amount"] for row in controller._loaded_candidates[source_id].rows],
                ["20", "40", "60"],
            )

            controller._project["query_parameters"][0]["current_value"] = "4"
            controller.refresh_source()
            self.assertEqual(
                [row["Scaled amount"] for row in controller._loaded_candidates[source_id].rows],
                ["40", "80", "120"],
            )

    def test_parameter_manager_and_refresh_commit_are_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sales.csv"
            path.write_text("Amount,Region\n10,East\n20,West\n30,East\n", encoding="utf-8")
            app = QApplication.instance() or self.app
            controller = StudioController(
                app, QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            )
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_id = controller.activeTableId
            first_stage = [{
                "name": "MinimumAmount", "type": "whole_number",
                "current_value": "15",
            }]

            def stage_session(dialog: TransformDataDialog, parameter_list: list[dict[str, str]]):
                def stage_manager(manager: ManageQueryParametersDialog):
                    manager._parameters = parameter_list
                    manager._accept_parameters()
                    return QDialog.DialogCode.Accepted

                with patch.object(ManageQueryParametersDialog, "exec", new=stage_manager):
                    dialog._manage_query_parameters()
                dialog._steps = [self.numeric_filter]
                dialog._step_metadata = [{}]
                dialog._preview_candidate = apply_transformations(
                    dialog._source_candidate, dialog._steps,
                    parameters=dialog._parameter_values(),
                )
                dialog._render_steps()
                dialog._refresh_preview()
                dialog._save_active_query_state()
                dialog._accept_candidate()
                return QDialog.DialogCode.Accepted

            with patch.object(
                TransformDataDialog, "exec",
                new=lambda dialog: stage_session(dialog, first_stage),
            ):
                self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)
            self.assertEqual(
                [row["Amount"] for row in controller._loaded_candidates[source_id].rows],
                ["20", "30"],
            )
            self.assertEqual(
                controller._project["data_sources"][0]["transform_steps"],
                [self.numeric_filter],
            )

            updated_stage = [{**first_stage[0], "current_value": "25"}]
            with patch.object(
                TransformDataDialog, "exec",
                new=lambda dialog: stage_session(dialog, updated_stage),
            ):
                self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)
            self.assertEqual(
                [row["Amount"] for row in controller._loaded_candidates[source_id].rows],
                ["30"],
            )
            controller.refresh_source()
            self.assertEqual(
                [row["Amount"] for row in controller._loaded_candidates[source_id].rows],
                ["30"],
            )


if __name__ == "__main__":
    unittest.main()
