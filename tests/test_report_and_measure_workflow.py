"""Controller integration tests for field-aware reporting and saved measures."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.inline_data import parse_pasted_table
from analytics_studio.measure_dialog import DAX_FUNCTION_TEMPLATES, MeasureDialog
from analytics_studio.measures import DAX_FUNCTION_NAMES, tokenize
from analytics_studio.project import validate_project


class ReportAndMeasureWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def populated_controller(self) -> StudioController:
        controller = self.controller()
        data = parse_pasted_table(
            "Date,Emirates,Sales,Cost,Quantity\n"
            "2026-08-01,Abu Dhabi,100.5,80,3\n"
            "2026-08-02,Dubai,200,150,2\n"
            "2026-09-01,Dubai,50,20,1",
            name="VAT sample",
        )
        self.assertTrue(controller._commit_inline(data))
        return controller

    def test_report_maps_sales_date_emirates_quantity_and_calculates_margin(self) -> None:
        controller = self.populated_controller()

        self.assertEqual(controller.reportKpis, {
            "Revenue": "350.50", "Cost": "250", "Margin": "100.50",
            "Units": "6", "Orders": "3",
        })
        self.assertEqual(controller.monthlySeries, [
            {"label": "2026-08", "value": 300.5},
            {"label": "2026-09", "value": 50.0},
        ])
        self.assertEqual(controller.regionSeries, [
            {"label": "Abu Dhabi", "value": 100.5},
            {"label": "Dubai", "value": 250.0},
        ])
        self.assertEqual(controller.regions, ["All regions", "Abu Dhabi", "Dubai"])

        controller.setRegionFilter("Dubai")

        self.assertEqual(controller.reportKpis["Revenue"], "250")
        self.assertEqual(controller.monthlySeries, [{"label": "2026-08", "value": 200.0}, {"label": "2026-09", "value": 50.0}])

    def test_missing_report_fields_produce_explanatory_messages(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(parse_pasted_table("Name\nA\nB")))

        self.assertEqual(controller.reportKpis["Revenue"], "—")
        self.assertIn("sales or revenue column", controller.monthlyChartMessage)
        self.assertIn("sales or revenue column", controller.regionChartMessage)

    def test_measures_are_evaluated_displayed_and_recomputed_after_save_reopen(self) -> None:
        controller = self.populated_controller()
        self.assertEqual(controller.activePageVisuals, [])
        self.assertTrue(controller.create_measure("Total Sales", "SUM([Sales])"))
        self.assertEqual(controller.activePageVisuals, [])
        self.assertTrue(controller.create_measure("Average Sale", "[Total Sales] / COUNTROWS()"))
        self.assertEqual(controller.reportKpis["Total Sales"], "350.50")
        self.assertEqual(controller.modelMeasures[1]["value"], "116.83")
        controller.add_visual("card", "Total Sales KPI", 14, 14, 120, 80)
        controller.add_visual("card", "Average Sale KPI", 148, 14, 120, 80)
        self.assertIn("Total Sales KPI", controller.activePageVisuals)
        self.assertEqual(controller.modelMeasures[0]["error"], "")

        path = self.root / "measures.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))

        self.assertEqual(reopened.modelMeasures[0]["value"], "350.50")
        self.assertEqual(reopened.modelMeasures[1]["value"], "116.83")
        self.assertIn("Average Sale KPI", reopened.activePageVisuals)

    def test_invalid_measure_is_transactional_and_quick_aggregate_expression_works(self) -> None:
        controller = self.populated_controller()
        before_project = controller._project.copy()
        dirty_before = controller.dirty

        self.assertFalse(controller.create_measure("Invalid", "CALCULATE()"))

        self.assertEqual(controller._project, before_project)
        self.assertEqual(controller.dirty, dirty_before)
        self.assertTrue(controller.create_measure("Quantity total", "SUM([Quantity])"))
        self.assertEqual(controller.reportKpis["Quantity total"], "6")

    def test_scalar_math_measures_persist_and_recompute(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure(
            "Rounded average", "ROUND(AVERAGE([Sales]), 1)"
        ))
        self.assertTrue(controller.create_measure(
            "Absolute loss", "ABS(MIN([Sales]) - 60)"
        ))
        self.assertEqual(controller.reportKpis["Rounded average"], "116.80")
        self.assertEqual(controller.reportKpis["Absolute loss"], "10")

        path = self.root / "scalar-math-measures.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.reportKpis["Rounded average"], "116.80")
        self.assertEqual(reopened.reportKpis["Absolute loss"], "10")

    def test_conditional_measures_follow_report_filter_and_reopen(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure(
            "Large sales", "IF(SUM([Sales]) >= 300, SUM([Sales]), 0)"
        ))
        self.assertTrue(controller.create_measure(
            "Sales threshold met", "IF([Large sales] > 0, 1, 0)"
        ))
        self.assertEqual(controller.reportKpis["Large sales"], "350.50")
        self.assertEqual(controller.reportKpis["Sales threshold met"], "1")

        controller.setRegionFilter("Dubai")
        self.assertEqual(controller.reportKpis["Large sales"], "0")
        self.assertEqual(controller.reportKpis["Sales threshold met"], "0")
        controller.setRegionFilter("All regions")

        path = self.root / "conditional-measures.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.reportKpis["Large sales"], "350.50")
        self.assertEqual(reopened.reportKpis["Sales threshold met"], "1")

    def test_row_context_measures_follow_filter_and_reopen(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure(
            "Line sales", "SUMX('VAT sample', [Sales] * [Quantity])"
        ))
        self.assertTrue(controller.create_measure(
            "Average line sales", "AVERAGEX('VAT sample', [Sales] * [Quantity])"
        ))
        self.assertTrue(controller.create_measure(
            "Count sales values", "COUNTX('VAT sample', [Sales])"
        ))
        self.assertTrue(controller.create_measure(
            "Count boolean results",
            "COUNTAX('VAT sample', IF([Sales] > 100, TRUE(), FALSE()))",
        ))
        self.assertTrue(controller.create_measure(
            "Ignore boolean results",
            "COUNTX('VAT sample', IF([Sales] > 100, TRUE(), FALSE()))",
        ))
        self.assertTrue(controller.create_measure("Numeric zero", "0"))
        self.assertEqual(controller.reportKpis["Line sales"], "751.50")
        self.assertEqual(controller.reportKpis["Average line sales"], "250.50")
        self.assertEqual(controller.reportKpis["Count sales values"], "3")
        self.assertEqual(controller.reportKpis["Count boolean results"], "3")
        self.assertEqual(controller.reportKpis["Ignore boolean results"], "—")
        self.assertEqual(controller.reportKpis["Numeric zero"], "0")

        controller.setRegionFilter("Dubai")
        self.assertEqual(controller.reportKpis["Line sales"], "450")
        self.assertEqual(controller.reportKpis["Average line sales"], "225")
        self.assertEqual(controller.reportKpis["Count sales values"], "2")
        self.assertEqual(controller.reportKpis["Count boolean results"], "2")
        self.assertEqual(controller.reportKpis["Ignore boolean results"], "—")
        self.assertEqual(controller.reportKpis["Numeric zero"], "0")
        controller.setRegionFilter("All regions")

        path = self.root / "iterator-measures.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.reportKpis["Line sales"], "751.50")
        self.assertEqual(reopened.reportKpis["Average line sales"], "250.50")
        self.assertEqual(reopened.reportKpis["Count sales values"], "3")
        self.assertEqual(reopened.reportKpis["Count boolean results"], "3")
        self.assertEqual(reopened.reportKpis["Ignore boolean results"], "—")
        self.assertEqual(reopened.reportKpis["Numeric zero"], "0")

    def test_blank_count_measure_previews_displays_and_refreshes(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text(
            "Region,Quarter,Sales\nNorth,Q1,\nSouth,Q1,\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        controller.setRegionFilter("North")
        project_before_preview = deepcopy(controller._project)
        kpis_before_preview = dict(controller.reportKpis)
        self.assertEqual(
            controller._preview_measure_expression(
                "Draft blank count", "COUNTX('sales', [Sales])"
            ),
            "—",
        )
        self.assertEqual(controller._project, project_before_preview)
        self.assertEqual(controller.currentRegion, "North")
        self.assertEqual(controller.reportKpis, kpis_before_preview)
        controller.setRegionFilter("All regions")
        self.assertTrue(controller.create_measure(
            "No sales value", "COUNTX('sales', [Sales])"
        ))
        self.assertTrue(controller.create_measure("Numeric zero", "0"))
        self.assertEqual(controller.reportKpis["No sales value"], "—")
        self.assertEqual(controller.modelMeasures[0]["error"], "")

        controller.add_visual("card", "Blank count card", 20, 20, 150, 90)
        blank_measure_binding = "__dax_measure__:No sales value"
        zero_measure_binding = "__dax_measure__:Numeric zero"
        controller.add_field_to_well("Fields", blank_measure_binding)
        self.assertEqual(controller.visualCardData("Blank count card")["value"], "—")
        controller.add_visual("column", "Blank count chart", 200, 20, 300, 200)
        controller.add_field_to_well("X-axis", "Region")
        controller.add_field_to_well("Y-axis", blank_measure_binding)
        self.assertEqual(controller.visualSeries("Blank count chart"), [])
        controller.add_visual("column", "Zero chart", 520, 20, 300, 200)
        controller.add_field_to_well("X-axis", "Region")
        controller.add_field_to_well("Y-axis", zero_measure_binding)
        self.assertEqual(controller.visualSeries("Zero chart"), [
            {"label": "North", "value": 0.0},
            {"label": "South", "value": 0.0},
        ])
        controller.add_visual("gauge", "Blank count gauge", 840, 240, 220, 200)
        controller.add_field_to_well("Value", blank_measure_binding)
        self.assertFalse(controller.visualGaugeData("Blank count gauge")["has_value"])
        controller.add_visual("kpi", "Blank count KPI", 1080, 240, 240, 200)
        controller.add_field_to_well("Indicator", blank_measure_binding)
        controller.add_field_to_well("Trend axis", "Quarter")
        self.assertFalse(controller.visualKpiData("Blank count KPI")["has_value"])
        controller.add_visual("matrix", "Blank count matrix", 840, 20, 300, 200)
        controller.add_field_to_well("Rows", "Region")
        controller.add_field_to_well("Columns", "Quarter")
        controller.add_field_to_well("Values", blank_measure_binding)
        self.assertEqual(controller.visualMatrixData("Blank count matrix"), {
            "columns": ["Region", "Q1"],
            "rows": [
                {"values": ["North", ""], "category": "North", "highlighted": False},
                {"values": ["South", ""], "category": "South", "highlighted": False},
            ],
            "total_rows": 2,
        })

        project_path = self.root / "blank-count.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["No sales value"], "—")
        self.assertEqual(reopened.visualCardData("Blank count card")["value"], "—")
        self.assertEqual(reopened.visualSeries("Blank count chart"), [])
        self.assertFalse(reopened.visualGaugeData("Blank count gauge")["has_value"])
        self.assertFalse(reopened.visualKpiData("Blank count KPI")["has_value"])
        self.assertEqual(reopened.visualMatrixData("Blank count matrix")["rows"][0]["values"], ["North", ""])

        source_path.write_text(
            "Region,Quarter,Sales\nNorth,Q1,11\nSouth,Q1,20\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["No sales value"], "2")
        self.assertEqual(reopened.visualCardData("Blank count card")["value"], "2")
        self.assertEqual(reopened.visualSeries("Blank count chart"), [
            {"label": "North", "value": 1.0},
            {"label": "South", "value": 1.0},
        ])
        self.assertTrue(reopened.visualGaugeData("Blank count gauge")["has_value"])
        self.assertEqual(reopened.visualKpiData("Blank count KPI")["value"], 2.0)
        self.assertEqual(reopened.visualMatrixData("Blank count matrix")["rows"][0]["values"], ["North", "1"])

    def test_related_measure_persists_and_recomputes_from_model_relationship(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(parse_pasted_table(
            "ProductKey,Quantity\n1,2\n2,3\n99,8", name="Sales"
        )))
        sales_id = controller._active_source_id
        self.assertTrue(controller._commit_inline(parse_pasted_table(
            "ProductKey,Unit Price\n1,10.50\n2,4", name="Products"
        )))
        products_id = controller._active_source_id
        sales = controller._model_table_for_source(controller._project, sales_id)
        products = controller._model_table_for_source(controller._project, products_id)
        relationship = {
            "relationship_version": 1,
            "id": "sales-products",
            "from": f"{sales['name']}[ProductKey]",
            "to": f"{products['name']}[ProductKey]",
            "from_table_id": sales_id,
            "from_column": "ProductKey",
            "to_table_id": products_id,
            "to_column": "ProductKey",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }
        accepted_relationship = controller._validate_relationship_candidate(
            [relationship]
        )
        next_project = deepcopy(controller._project)
        next_project["model"]["relationships"] = accepted_relationship
        controller._project = validate_project(next_project)
        controller._refresh_model_view()
        controller._refresh_report()

        expression = (
            f"SUMX('{sales['name']}', '{sales['name']}'[Quantity] * "
            f"RELATED('{products['name']}'[Unit Price]))"
        )
        self.assertTrue(controller.create_measure("Revenue", expression))
        self.assertEqual(controller.reportKpis["Revenue"], "33")

        path = self.root / "related-measure.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.reportKpis["Revenue"], "33")
        reopened_products_id = next(
            table["id"] for table in reopened._project["model"]["tables"]
            if table["name"] == "Products"
        )
        reopened_relationship = reopened._project["model"]["relationships"][0]
        self.assertEqual(reopened_relationship["to_table_id"], reopened_products_id)

    def test_related_measure_recomputes_after_lookup_source_refresh(self) -> None:
        sales_path = self.root / "Sales.csv"
        products_path = self.root / "Products.csv"
        sales_path.write_text(
            "ProductKey,Quantity\n1,2\n2,3\n", encoding="utf-8"
        )
        products_path.write_text(
            "ProductKey,Unit Price\n1,10.50\n2,4\n", encoding="utf-8"
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = controller._active_source_id
        self.assertTrue(
            controller._commit_import(products_path, parse_file(products_path))
        )
        products_id = controller._active_source_id
        sales = controller._model_table_for_source(controller._project, sales_id)
        products = controller._model_table_for_source(controller._project, products_id)
        relationship = {
            "relationship_version": 1,
            "id": "sales-products",
            "from": f"{sales['name']}[ProductKey]",
            "to": f"{products['name']}[ProductKey]",
            "from_table_id": sales_id,
            "from_column": "ProductKey",
            "to_table_id": products_id,
            "to_column": "ProductKey",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }
        next_project = deepcopy(controller._project)
        next_project["model"]["relationships"] = (
            controller._validate_relationship_candidate([relationship])
        )
        controller._project = validate_project(next_project)
        controller._refresh_model_view()
        controller._refresh_report()
        expression = (
            f"SUMX('{sales['name']}', '{sales['name']}'[Quantity] * "
            f"RELATED('{products['name']}'[Unit Price]))"
        )
        self.assertTrue(controller.create_measure("Revenue", expression))
        self.assertEqual(controller.reportKpis["Revenue"], "33")

        project_path = self.root / "related-refresh.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        refreshed_products_path = self.root / "Products.csv"
        refreshed_products_path.write_text(
            "ProductKey,Unit Price\n1,12\n2,6\n", encoding="utf-8"
        )
        self.assertTrue(reopened.selectTable(products_id))
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Revenue"], "42")

    def test_related_text_key_refresh_uses_shared_collation_and_rejects_collisions(self) -> None:
        sales_path = self.root / "Sales Text Keys.csv"
        products_path = self.root / "Products Text Keys.csv"
        sales_path.write_text(
            "ProductKey,Quantity\na,2\nb,3\n", encoding="utf-8"
        )
        products_path.write_text(
            "ProductKey,Unit Price\nA,10.50\nB,4\n", encoding="utf-8"
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = controller._active_source_id
        self.assertTrue(
            controller._commit_import(products_path, parse_file(products_path))
        )
        products_id = controller._active_source_id
        sales = controller._model_table_for_source(controller._project, sales_id)
        products = controller._model_table_for_source(controller._project, products_id)
        relationship = {
            "relationship_version": 1,
            "id": "sales-products",
            "from": f"{sales['name']}[ProductKey]",
            "to": f"{products['name']}[ProductKey]",
            "from_table_id": sales_id,
            "from_column": "ProductKey",
            "to_table_id": products_id,
            "to_column": "ProductKey",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }
        next_project = deepcopy(controller._project)
        next_project["model"]["relationships"] = (
            controller._validate_relationship_candidate([relationship])
        )
        controller._project = validate_project(next_project)
        controller._refresh_model_view()
        controller._refresh_report()
        expression = (
            f"SUMX('{sales['name']}', '{sales['name']}'[Quantity] * "
            f"RELATED('{products['name']}'[Unit Price]))"
        )
        self.assertTrue(controller.create_measure("Revenue", expression))
        self.assertEqual(controller.reportKpis["Revenue"], "33")

        project_path = self.root / "related-text-refresh.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertTrue(reopened.selectTable(products_id))
        reopened_products_path = self.root / "Products Text Keys.csv"
        reopened_products_path.write_text(
            "ProductKey,Unit Price\nA,12\na,99\nB,6\n", encoding="utf-8"
        )
        project_before = deepcopy(reopened._project)
        loaded_before = deepcopy(reopened._loaded_candidates)
        raw_before = deepcopy(reopened._raw_candidates)
        with patch("analytics_studio.controller.QMessageBox.critical") as critical:
            reopened.refresh_source()
        critical.assert_called_once()
        self.assertEqual(reopened._project, project_before)
        self.assertEqual(reopened._loaded_candidates, loaded_before)
        self.assertEqual(reopened._raw_candidates, raw_before)
        self.assertEqual(reopened.reportKpis["Revenue"], "33")

        reopened_products_path.write_text(
            "ProductKey,Unit Price\nA,12\nB,6\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Revenue"], "42")

    def test_new_measure_and_quick_measure_dialogs_return_valid_definitions(self) -> None:
        formula_dialog = MeasureDialog(["Date", "Sales"], [])
        formula_dialog.name_edit.setText("Total Sales")
        formula_dialog.expression_edit.setPlainText("SUM([Sales])")
        self.assertTrue(formula_dialog.save_button.isEnabled())
        formula_dialog._accept_measure()
        self.assertEqual(formula_dialog.measure, {
            "name": "Total Sales", "expression": "SUM([Sales])",
        })

        quick_dialog = MeasureDialog(
            ["Date", "Sales"], [], quick=True, default_column="Sales"
        )
        self.assertEqual(quick_dialog.column_combo.currentText(), "Sales")
        quick_dialog._accept_measure()
        self.assertEqual(quick_dialog.measure, {
            "name": "Sum of Sales", "expression": "SUM([Sales])",
        })

        quick_distinct = MeasureDialog(
            ["Sales"], [], quick=True, default_column="Sales"
        )
        quick_distinct.function_combo.setCurrentIndex(
            quick_distinct.function_combo.findData("DISTINCTCOUNTNOBLANK")
        )
        quick_distinct._accept_measure()
        self.assertEqual(quick_distinct.measure, {
            "name": "Distinct count without blank of Sales",
            "expression": "DISTINCTCOUNTNOBLANK([Sales])",
        })

    def test_measure_editor_searches_inserts_and_previews_supported_dax(self) -> None:
        self.assertEqual(set(DAX_FUNCTION_TEMPLATES), set(DAX_FUNCTION_NAMES))
        previews = []
        dialog = MeasureDialog(
            ["Sales"], [],
            field_references=[("VAT sample[Sales]", "'VAT sample'[Sales]")],
            measure_references=["Existing total"],
            preview_callback=lambda name, expression: previews.append(
                (name, expression)
            ) or "350.50",
        )
        dialog.name_edit.setText("Draft total")
        dialog.expression_edit.setPlainText("Replace this formula")
        selection = dialog.expression_edit.textCursor()
        selection.select(QTextCursor.SelectionType.Document)
        dialog.expression_edit.setTextCursor(selection)
        dialog.function_combo.setCurrentText("SUM")
        dialog.insert_function_button.click()
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM([Column])")
        self.assertEqual(dialog.expression_edit.textCursor().selectedText(), "[Column]")
        self.assertIn("SUM([Column])", dialog.function_signature_label.text())
        for parser_form in ("BLANK", "DISTINCT", "FALSE", "TRUE"):
            self.assertIn(parser_form, DAX_FUNCTION_NAMES)

        dialog.field_combo.setCurrentIndex(
            dialog.field_combo.findData("'VAT sample'[Sales]")
        )
        dialog.insert_field_button.click()
        self.assertEqual(
            dialog.expression_edit.toPlainText(), "SUM('VAT sample'[Sales])"
        )
        dialog.measure_combo.setCurrentIndex(
            dialog.measure_combo.findData("[Existing total]")
        )
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog.expression_edit.insertPlainText(" + ")
        dialog.insert_measure_button.click()
        dialog.preview_button.click()

        self.assertEqual(previews, [(
            "Draft total", "SUM('VAT sample'[Sales]) + [Existing total]",
        )])
        self.assertEqual(dialog.preview_label.text(), "Current report-context result: 350.50")
        dialog.expression_edit.clear()
        dialog.function_combo.setCurrentText("RELATED")
        dialog.insert_function_button.click()
        self.assertEqual(
            dialog.expression_edit.toPlainText(),
            "RELATED('Related table'[Column])",
        )
        dialog.expression_edit.clear()
        dialog.function_combo.setCurrentText("DISTINCTCOUNTNOBLANK")
        dialog.insert_function_button.click()
        self.assertEqual(
            dialog.expression_edit.toPlainText(),
            "DISTINCTCOUNTNOBLANK([Column])",
        )
        self.assertEqual(
            dialog.expression_edit.textCursor().selectedText(), "[Column]"
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_distinct_count_without_blank_editor_preview_and_create_flow(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Value\nA\nA\nB", name="DAX values")
        ))
        dialog = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=controller._preview_measure_expression,
        )
        dialog.name_edit.setText("Unique values without blank")
        dialog.function_combo.setCurrentText("DISTINCTCOUNTNOBLANK")
        dialog.insert_function_button.click()
        field_index = dialog.field_combo.findData("'DAX values'[Value]")
        self.assertGreaterEqual(field_index, 0)
        dialog.field_combo.setCurrentIndex(field_index)
        dialog.insert_field_button.click()
        self.assertEqual(
            dialog.expression_edit.toPlainText(),
            "DISTINCTCOUNTNOBLANK('DAX values'[Value])",
        )

        dialog.preview_button.click()
        self.assertEqual(
            dialog.preview_label.text(),
            "Current report-context result: 2",
        )
        dialog.save_button.click()
        self.assertEqual(dialog.measure, {
            "name": "Unique values without blank",
            "expression": "DISTINCTCOUNTNOBLANK('DAX values'[Value])",
        })
        self.assertTrue(controller.create_measure(
            dialog.measure["name"], dialog.measure["expression"]
        ))
        self.assertEqual(
            controller.reportKpis["Unique values without blank"], "2"
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_distinct_count_blank_semantics_persist_and_refresh(self) -> None:
        source_path = self.root / "distinct-count.csv"
        source_path.write_text(
            "Region,Value\nNorth,\nSouth,\nWest, \nEast,0\nDubai,0\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        self.assertTrue(controller.create_measure(
            "Distinct values", "DISTINCTCOUNT([Value])"
        ))
        self.assertTrue(controller.create_measure(
            "Distinct values without blank", "DISTINCTCOUNTNOBLANK([Value])"
        ))
        self.assertTrue(controller.create_measure(
            "No matching values",
            'CALCULATE(DISTINCTCOUNT([Value]), [Region] = "Missing")',
        ))
        self.assertEqual(controller.reportKpis["Distinct values"], "3")
        self.assertEqual(controller.reportKpis["Distinct values without blank"], "2")
        self.assertEqual(controller.reportKpis["No matching values"], "—")

        controller.add_visual("card", "Distinct blank card", 20, 20, 150, 90)
        controller.add_field_to_well(
            "Fields", "__dax_measure__:Distinct values"
        )
        self.assertEqual(
            controller.visualCardData("Distinct blank card")["value"], "3"
        )
        controller.add_visual("card", "Distinct no-blank card", 190, 20, 150, 90)
        controller.add_field_to_well(
            "Fields", "__dax_measure__:Distinct values without blank"
        )
        self.assertEqual(
            controller.visualCardData("Distinct no-blank card")["value"], "2"
        )

        project_path = self.root / "distinct-count.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Distinct values"], "3")
        self.assertEqual(reopened.reportKpis["Distinct values without blank"], "2")
        self.assertEqual(reopened.reportKpis["No matching values"], "—")
        self.assertEqual(
            reopened.visualCardData("Distinct blank card")["value"], "3"
        )
        self.assertEqual(
            reopened.visualCardData("Distinct no-blank card")["value"], "2"
        )

        source_path.write_text(
            "Region,Value\nNorth,0\nSouth,10\nWest,10\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Distinct values"], "2")
        self.assertEqual(reopened.reportKpis["Distinct values without blank"], "2")
        self.assertEqual(reopened.reportKpis["No matching values"], "—")
        self.assertEqual(
            reopened.visualCardData("Distinct no-blank card")["value"], "2"
        )

    def test_measure_preview_uses_loaded_tables_without_mutating_project(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Value\n2", name="O'Brien")
        ))
        references = controller._dax_field_references()
        self.assertIn(("VAT sample[Sales]", "'VAT sample'[Sales]"), references)
        self.assertIn(("O'Brien[Value]", "'O''Brien'[Value]"), references)
        for warm_cache in (False, True):
            if warm_cache:
                controller._report_filter_context()
            else:
                controller._report_filter_context_cache.clear()
            controller._region_column = "previous region binding"
            controller._filter_context_error = "previous aggregated filter error"
            project_before = deepcopy(controller._project)
            dirty_before = controller._dirty
            cache_before = deepcopy(controller._report_filter_context_cache)

            self.assertEqual(
                controller._preview_measure_expression(
                    "Draft total", "SUM('VAT sample'[Sales])"
                ),
                "350.50",
            )
            self.assertEqual(controller._project, project_before)
            self.assertEqual(controller._dirty, dirty_before)
            self.assertEqual(controller._report_filter_context_cache, cache_before)
            self.assertEqual(controller._region_column, "previous region binding")
            self.assertEqual(
                controller.filterContextError,
                "previous aggregated filter error",
            )

    def test_dax_picker_reference_resolves_table_names_containing_brackets(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Value\n10", name="T")
        ))
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Value\n99", name="T[archive]")
        ))

        references = controller._dax_field_references()
        self.assertIn(("T[archive][Value]", "'T[archive]'[Value]"), references)
        self.assertEqual(tokenize("SUM('T[archive]'[Value])")[2].value, "T[archive]\0Value")
        self.assertEqual(
            controller._preview_measure_expression(
                "Archive total", "SUM('T[archive]'[Value])"
            ),
            "99",
        )

    def test_measure_editor_can_open_an_existing_definition(self) -> None:
        dialog = MeasureDialog(
            ["Date", "Sales"], ["Total Sales"],
            initial_measure={
                "name": "Total Sales", "expression": "SUM([Sales])",
                "description": "Net sales", "display_folder": "Finance/Sales",
                "is_hidden": True,
            },
        )

        self.assertEqual(dialog.name_edit.text(), "Total Sales")
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM([Sales])")
        self.assertEqual(dialog.description_edit.toPlainText(), "Net sales")
        self.assertEqual(dialog.display_folder_edit.text(), "Finance/Sales")
        self.assertTrue(dialog.hidden_checkbox.isChecked())
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertEqual(dialog.save_button.text(), "Save measure")
        self.assertLessEqual(dialog.help_scroll_area.maximumHeight(), 132)

        dialog.expression_edit.setPlainText("SUM([Sales]) * 2")
        dialog.save_button.click()
        self.assertEqual(dialog.measure, {
            "name": "Total Sales", "expression": "SUM([Sales]) * 2",
            "description": "Net sales", "display_folder": "Finance/Sales",
            "is_hidden": True,
        })

    def test_measure_metadata_persists_and_hidden_measures_stay_formula_visible(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure(
            "Base Sales", "SUM([Sales])", description="Source total",
            display_folder="Finance/Sales", is_hidden=True,
        ))
        self.assertTrue(controller.create_measure(
            "Double Sales", "[Base Sales] * 2",
            description="Twice the base total", display_folder="Finance/Analysis",
        ))
        self.assertNotIn("__dax_measure__:Base Sales", controller.filteredFields)
        self.assertIn("__dax_measure__:Double Sales", controller.filteredFields)
        self.assertEqual(
            controller.visualFieldLabel("__dax_measure__:Double Sales"),
            "Measure · Double Sales",
        )
        self.assertNotIn("Base Sales", controller.reportKpiNames)
        self.assertIn("Double Sales", controller.reportKpiNames)
        self.assertEqual(controller.modelMeasures[0]["description"], "Source total")
        self.assertEqual(controller.modelMeasures[0]["display_folder"], "Finance/Sales")
        self.assertTrue(controller.modelMeasures[0]["is_hidden"])
        self.assertEqual(controller.reportKpis["Double Sales"], "701")

        self.assertTrue(controller.update_measure(
            "Base Sales", "Base Sales", "SUM([Sales])",
            description="Visible source total", display_folder="Finance", is_hidden=False,
        ))
        self.assertIn("__dax_measure__:Base Sales", controller.filteredFields)
        self.assertIn("Base Sales", controller.reportKpiNames)
        path = self.root / "measure-metadata.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.modelMeasures[0]["description"], "Visible source total")
        self.assertEqual(reopened.modelMeasures[0]["display_folder"], "Finance")
        self.assertFalse(reopened.modelMeasures[0]["is_hidden"])
        self.assertEqual(reopened.reportKpis["Double Sales"], "701")
        self.assertTrue(reopened.update_measure(
            "Base Sales", "Base Sales", "SUM([Sales]) * 1"
        ))
        self.assertEqual(reopened.modelMeasures[0]["description"], "Visible source total")
        self.assertEqual(reopened.modelMeasures[0]["display_folder"], "Finance")

    def test_edit_measure_updates_value_and_save_reopen(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure("Total Sales", "SUM([Sales])"))
        self.assertTrue(controller.update_measure(
            "Total Sales", "Doubled Sales", "SUM([Sales]) * 2"
        ), controller.statusMessage)
        self.assertEqual(controller.modelMeasures[0]["name"], "Doubled Sales")
        self.assertEqual(controller.modelMeasures[0]["expression"], "SUM([Sales]) * 2")
        self.assertEqual(controller.modelMeasures[0]["value"], "701")

        path = self.root / "edited-measure.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.modelMeasures[0]["name"], "Doubled Sales")
        self.assertEqual(reopened.modelMeasures[0]["value"], "701")

    def test_measure_rename_and_delete_preserve_dependents(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure("Base Sales", "SUM([Sales])"))
        self.assertTrue(controller.create_measure("Double Sales", "[Base Sales] * 2"))

        self.assertFalse(controller.update_measure(
            "Base Sales", "Renamed Sales", "SUM([Sales])"
        ))
        self.assertIn("Could not update measure", controller.statusMessage)
        self.assertEqual(controller.modelMeasures[0]["name"], "Base Sales")
        self.assertFalse(controller.remove_measure("Base Sales"))
        self.assertIn("Could not delete measure", controller.statusMessage)
        self.assertTrue(controller.remove_measure("Double Sales"))
        self.assertTrue(controller.remove_measure("Base Sales"))
        self.assertEqual(controller.modelMeasures, [])


if __name__ == "__main__":
    unittest.main()
