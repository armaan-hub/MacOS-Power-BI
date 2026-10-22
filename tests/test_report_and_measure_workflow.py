"""Controller integration tests for field-aware reporting and saved measures."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

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

    def test_screenshot_average_formula_matches_filtered_visual_context(self) -> None:
        controller = self.populated_controller()
        expression = "SUM([Sales]) / COUNTROWS()"
        draft = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=controller._preview_measure_expression,
        )
        draft.name_edit.setText("Draft Average Sales")
        draft.expression_edit.setPlainText(expression)
        draft.preview_button.click()
        self.assertEqual(
            draft.preview_label.text(),
            "Current report-context result: 116.83",
        )
        draft.deleteLater()
        self.app.processEvents()

        def accept_screenshot_measure(dialog: MeasureDialog) -> int:
            dialog.name_edit.setText("Average Sales")
            dialog.expression_edit.setPlainText(expression)
            dialog.preview_button.click()
            self.assertEqual(
                dialog.preview_label.text(),
                "Current report-context result: 116.83",
            )
            dialog.save_button.click()
            return dialog.result()

        with patch.object(MeasureDialog, "exec", new=accept_screenshot_measure):
            self.assertTrue(controller.new_measure_dialog(), controller.statusMessage)
        self.assertEqual(controller.modelMeasures[0]["value"], "116.83")

        measure_binding = "__dax_measure__:Average Sales"
        controller.add_visual("card", "Average sales card", 20, 20, 160, 90)
        controller.add_field_to_well("Fields", measure_binding)
        self.assertEqual(controller.visualCardData("Average sales card")["value"], "116.83")

        controller.add_visual("column", "Average sales by emirate", 200, 20, 360, 240)
        controller.add_field_to_well("X-axis", "Emirates")
        controller.add_field_to_well("Y-axis", measure_binding)
        self.assertEqual(controller.visualSeries("Average sales by emirate"), [
            {"label": "Abu Dhabi", "value": 100.5},
            {"label": "Dubai", "value": 125.0},
        ])

        self.assertTrue(controller.addPageFilterRule(
            str(controller.activeTableId), "Emirates", "equals", "Dubai", "", "", "and"
        ))
        filtered_draft = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=controller._preview_measure_expression,
        )
        filtered_draft.name_edit.setText("Filtered Draft Average Sales")
        filtered_draft.expression_edit.setPlainText(expression)
        filtered_draft.preview_button.click()
        self.assertEqual(
            filtered_draft.preview_label.text(),
            "Current report-context result: 125",
        )
        filtered_draft.deleteLater()
        self.app.processEvents()
        self.assertEqual(controller.modelMeasures[0]["value"], "125")
        self.assertEqual(controller.visualCardData("Average sales card")["value"], "125")
        self.assertEqual(controller.visualSeries("Average sales by emirate"), [
            {"label": "Dubai", "value": 125.0},
        ])

        project_path = self.root / "screenshot-average.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.modelMeasures[0]["expression"], expression)
        self.assertEqual(reopened.modelMeasures[0]["value"], "125")
        self.assertEqual(reopened.visualCardData("Average sales card")["value"], "125")
        self.assertEqual(reopened.visualSeries("Average sales by emirate"), [
            {"label": "Dubai", "value": 125.0},
        ])

    def test_measure_home_table_survives_table_switch_and_project_reopen(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text("Amount\n10\n20\n", encoding="utf-8")
        targets_path = self.root / "Targets.csv"
        targets_path.write_text("Amount\n99\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_source_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(targets_path, parse_file(targets_path)))
        targets_source_id = str(controller.activeTableId)
        self.assertTrue(controller.selectTable(sales_source_id))

        self.assertTrue(controller.create_measure("Sales total", "SUM([Amount])"))
        self.assertTrue(controller.create_measure("Sales rows", "COUNTROWS()"))
        sales_table_id = str(controller._active_model_table_id())
        for measure in controller._project["model"]["measures"]:
            self.assertEqual(measure["home_table_id"], sales_table_id)

        self.assertTrue(controller.selectTable(targets_source_id))
        self.assertEqual(controller._measure_values["Sales total"], "30")
        self.assertEqual(controller._measure_values["Sales rows"], "2")

        project_path = self.root / "home-table.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._measure_values["Sales total"], "30")
        self.assertEqual(reopened._measure_values["Sales rows"], "2")

        with patch("analytics_studio.controller.QMessageBox.warning") as warning:
            self.assertFalse(reopened.removeTable(sales_source_id))
        warning.assert_called_once()

    def test_unsupported_local_measure_is_transactional_and_quick_aggregate_expression_works(self) -> None:
        controller = self.populated_controller()
        before_project = deepcopy(controller._project)
        dirty_before = controller.dirty

        self.assertFalse(controller.create_measure("Invalid", "CALCULATE()"))

        self.assertEqual(controller._project, before_project)
        self.assertEqual(controller.dirty, dirty_before)
        # Power BI refuses a direct CALCULATE inside a CALCULATE Boolean filter ("A function 'CALCULATE' has been used in
        # a True/False expression", tools/parity/dax_battery_boolean_scalar_rhs.json), so the local engine does too.
        self.assertFalse(controller.create_measure(
            "Unsupported local filter value",
            "CALCULATE(COUNTROWS('VAT sample'), 'VAT sample'[Quantity] > CALCULATE(COUNTROWS('VAT sample')))",
        ))
        self.assertTrue(controller.statusMessage)
        self.assertEqual(controller._project, before_project)
        self.assertEqual(controller.dirty, dirty_before)
        # ...while the row count of another column's values on the right of a comparison is accepted, as in Power BI
        # (answer 2 for the same shape on Facts, tools/parity/dax_battery_adversarial.json).
        self.assertTrue(controller.create_measure(
            "Quantity above value count",
            "CALCULATE(COUNTROWS('VAT sample'), 'VAT sample'[Quantity] > COUNTROWS(VALUES('VAT sample'[Sales])))",
        ))
        self.assertTrue(controller.create_measure("Quantity total", "SUM([Quantity])"))
        self.assertEqual(controller.reportKpis["Quantity total"], "6")

    def test_divide_coalesce_measure_previews_displays_persists_and_refreshes(self) -> None:
        source_path = self.root / "fallback-sales.csv"
        source_path.write_text(
            "Numerator,Denominator\n10,0\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        expression = "COALESCE(DIVIDE(SUM([Numerator]), SUM([Denominator])), 7)"
        project_before_preview = deepcopy(controller._project)
        dialog = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=controller._preview_measure_expression,
        )
        dialog.name_edit.setText("Safe rate")
        dialog.function_combo.setCurrentText("COALESCE")
        dialog.insert_function_button.click()
        dialog.expression_edit.textCursor().insertText(
            "DIVIDE(SUM([Numerator]), SUM([Denominator]))"
        )
        expression_cursor = dialog.expression_edit.textCursor()
        formula_draft = dialog.expression_edit.toPlainText()
        fallback_start = formula_draft.index("expression2")
        expression_cursor.setPosition(fallback_start)
        expression_cursor.setPosition(
            fallback_start + len("expression2"),
            QTextCursor.MoveMode.KeepAnchor,
        )
        dialog.expression_edit.setTextCursor(expression_cursor)
        expression_cursor.insertText("7")
        self.assertEqual(dialog.expression_edit.toPlainText(), expression)
        dialog.show()
        self.app.processEvents()
        dialog.preview_button.click()
        self.assertEqual(
            dialog.preview_label.text(), "Current report-context result: 7"
        )
        self.assertEqual(controller._project, project_before_preview)
        dialog.save_button.click()
        self.assertEqual(dialog.measure, {"name": "Safe rate", "expression": expression})
        self.assertTrue(controller.create_measure(
            dialog.measure["name"], dialog.measure["expression"]
        ))
        dialog.deleteLater()
        self.app.processEvents()
        self.assertEqual(controller.reportKpis["Safe rate"], "7")
        controller.add_visual("card", "Safe rate card", 20, 20, 150, 90)
        controller.add_field_to_well("Fields", "__dax_measure__:Safe rate")
        self.assertEqual(controller.visualCardData("Safe rate card")["value"], "7")

        project_path = self.root / "coalesce-measure.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Safe rate"], "7")
        self.assertEqual(reopened.visualCardData("Safe rate card")["value"], "7")

        source_path.write_text(
            "Numerator,Denominator\n10,2\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Safe rate"], "5")
        self.assertEqual(reopened.visualCardData("Safe rate card")["value"], "5")

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

    def test_maxx_minx_measures_persist_into_cards_and_recompute_after_refresh(self) -> None:
        source_path = self.root / "amounts.csv"
        source_path.write_text(
            "Amount\n-2.5\n0\n9.75\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        table_name = str(controller.tableCatalog[0]["name"])

        for measure_name, function, expected in (
            ("Highest amount", "MAXX", "9.75"),
            ("Lowest amount", "MINX", "-2.50"),
        ):
            expression = f"{function}('{table_name}', [Amount])"
            dialog = MeasureDialog(
                list(controller.headers), [],
                field_references=controller._dax_field_references(),
                preview_callback=controller._preview_measure_expression,
            )
            dialog.name_edit.setText(measure_name)
            dialog.expression_edit.setPlainText(expression)
            dialog.preview_button.click()
            self.assertEqual(
                dialog.preview_label.text(),
                f"Current report-context result: {expected}",
            )
            dialog.save_button.click()
            self.assertEqual(
                dialog.measure, {"name": measure_name, "expression": expression}
            )
            self.assertTrue(controller.create_measure(
                dialog.measure["name"], dialog.measure["expression"]
            ))
            dialog.deleteLater()
            self.app.processEvents()

        self.assertEqual(controller.reportKpis["Highest amount"], "9.75")
        self.assertEqual(controller.reportKpis["Lowest amount"], "-2.50")

        controller.add_visual("card", "Highest amount card", 20, 20, 150, 90)
        controller.add_field_to_well("Fields", "__dax_measure__:Highest amount")
        controller.add_visual("card", "Lowest amount card", 190, 20, 150, 90)
        controller.add_field_to_well("Fields", "__dax_measure__:Lowest amount")
        self.assertEqual(
            controller.visualCardData("Highest amount card")["value"], "9.75"
        )
        self.assertEqual(
            controller.visualCardData("Lowest amount card")["value"], "-2.50"
        )

        project_path = self.root / "extrema-measures.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Highest amount"], "9.75")
        self.assertEqual(reopened.reportKpis["Lowest amount"], "-2.50")

        source_path.write_text(
            "Amount\n4.25\n8\n1\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Highest amount"], "8")
        self.assertEqual(reopened.reportKpis["Lowest amount"], "1")
        self.assertEqual(
            reopened.visualCardData("Highest amount card")["value"], "8"
        )
        self.assertEqual(
            reopened.visualCardData("Lowest amount card")["value"], "1"
        )

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
        # Power BI 2.157.879.0 refuses a Boolean value in COUNTX (tools/parity/dax_battery_comments_booleans.json)
        self.assertFalse(controller.create_measure(
            "Boolean countx",
            "COUNTX('VAT sample', IF([Sales] > 100, TRUE(), FALSE()))",
        ))
        self.assertTrue(controller.create_measure("Numeric zero", "0"))
        self.assertEqual(controller.reportKpis["Line sales"], "751.50")
        self.assertEqual(controller.reportKpis["Average line sales"], "250.50")
        self.assertEqual(controller.reportKpis["Count sales values"], "3")
        self.assertEqual(controller.reportKpis["Count boolean results"], "3")
        self.assertEqual(controller.reportKpis["Numeric zero"], "0")

        controller.setRegionFilter("Dubai")
        self.assertEqual(controller.reportKpis["Line sales"], "450")
        self.assertEqual(controller.reportKpis["Average line sales"], "225")
        self.assertEqual(controller.reportKpis["Count sales values"], "2")
        self.assertEqual(controller.reportKpis["Count boolean results"], "2")
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
            ["Date", "Sales"], [], quick=True, default_column="Sales",
            quick_table_name="Sales", quick_table_display_name="Finance / Sales",
        )
        self.assertEqual(quick_dialog.column_combo.currentText(), "Sales")
        self.assertEqual(
            quick_dialog.quick_table_context.text(), "Using table: Finance / Sales"
        )
        quick_dialog._accept_measure()
        self.assertEqual(quick_dialog.measure, {
            "name": "Sum of Sales", "expression": "SUM('Sales'[Sales])",
        })

        quick_distinct = MeasureDialog(
            ["Sales"], [], quick=True, default_column="Sales",
            quick_table_name="O'Brien", quick_table_display_name="Finance / O'Brien",
        )
        quick_distinct.function_combo.setCurrentIndex(
            quick_distinct.function_combo.findData("DISTINCTCOUNTNOBLANK")
        )
        quick_distinct._accept_measure()
        self.assertEqual(quick_distinct.measure, {
            "name": "Distinct count without blank of Sales",
            "expression": "DISTINCTCOUNTNOBLANK('O''Brien'[Sales])",
        })

        missing_table = MeasureDialog(
            ["Sales"], [], quick=True, default_column="Sales"
        )
        self.assertFalse(missing_table.save_button.isEnabled())
        self.assertIn("model table", missing_table.error_label.text().casefold())
        missing_table._accept_measure()
        self.assertIsNone(missing_table.measure)

    def test_quick_measure_stays_bound_to_source_through_switch_reopen_and_refresh(self) -> None:
        orders_path = self.root / "Orders.csv"
        targets_path = self.root / "Targets.csv"
        orders_path.write_text("Amount\n10\n20\n", encoding="utf-8")
        targets_path.write_text("Amount\n1000\n", encoding="utf-8")

        controller = self.controller()
        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = controller._active_source_id
        self.assertTrue(controller._commit_import(targets_path, parse_file(targets_path)))
        targets_id = controller._active_source_id
        self.assertTrue(controller.selectTable(orders_id))

        def accept_quick_measure(dialog: MeasureDialog) -> int:
            dialog._accept_measure()
            return int(dialog.result())

        with patch.object(MeasureDialog, "exec", new=accept_quick_measure):
            self.assertTrue(controller.quick_measure_dialog())
        self.assertEqual(controller.reportKpis["Sum of Amount"], "30")
        self.assertTrue(controller.selectTable(targets_id))
        self.assertEqual(
            controller.reportKpis["Sum of Amount"], "30",
            "Quick Measure must stay bound to the table where it was created",
        )
        self.assertEqual(
            controller.modelMeasures[0]["expression"], "SUM('Orders'[Amount])"
        )

        project_path = self.root / "quick-measure-table-binding.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertTrue(reopened.selectTable(targets_id))
        self.assertEqual(reopened.reportKpis["Sum of Amount"], "30")
        self.assertEqual(
            reopened.modelMeasures[0]["expression"], "SUM('Orders'[Amount])"
        )

        orders_path.write_text("Amount\n10\n25\n", encoding="utf-8")
        self.assertTrue(reopened.selectTable(orders_id))
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Sum of Amount"], "35")
        self.assertTrue(reopened.selectTable(targets_id))
        self.assertEqual(reopened.reportKpis["Sum of Amount"], "35")

    def test_quick_measure_requires_active_loaded_model_table_mapping(self) -> None:
        source_path = self.root / "orphaned-source.csv"
        source_path.write_text("Amount\n10\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        project_before = deepcopy(controller._project)
        dirty_before = controller.dirty
        controller._table_catalog = []

        with patch("analytics_studio.controller.MeasureDialog") as dialog_type:
            self.assertFalse(controller.quick_measure_dialog())

        dialog_type.assert_not_called()
        self.assertIn("loaded model table", controller.statusMessage.casefold())
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller.dirty, dirty_before)

    def test_measure_save_rejects_evaluation_errors_and_keeps_the_draft_open(self) -> None:
        controller = self.populated_controller()
        before_project = deepcopy(controller._project)
        dirty_before = controller.dirty
        dialog = MeasureDialog(
            list(controller.headers), [],
            preview_callback=controller._preview_measure_expression,
        )
        dialog.name_edit.setText("Unsupported draft")
        expression = "RELATED('VAT sample'[Sales])"
        dialog.expression_edit.setPlainText(expression)
        dialog.show()
        self.app.processEvents()

        dialog.save_button.click()
        self.app.processEvents()

        self.assertTrue(dialog.isVisible())
        self.assertIsNone(dialog.measure)
        self.assertEqual(dialog.name_edit.text(), "Unsupported draft")
        self.assertEqual(dialog.expression_edit.toPlainText(), expression)
        self.assertIn("row context", dialog.preview_label.text())
        self.assertEqual(controller._project, before_project)
        self.assertEqual(controller.dirty, dirty_before)
        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()

    def test_measure_save_rechecks_the_latest_draft_before_accepting(self) -> None:
        calls = []

        def preview(name: str, expression: str) -> str:
            calls.append((name, expression))
            return "Current result: 42"

        dialog = MeasureDialog(["Sales"], [], preview_callback=preview)
        dialog.name_edit.setText("Latest draft")
        dialog.expression_edit.setPlainText("SUM([Sales])")
        dialog.show()
        self.app.processEvents()
        dialog.preview_button.click()
        dialog.expression_edit.setPlainText("SUM([Sales]) + 1")

        dialog.save_button.click()

        self.assertEqual(calls, [
            ("Latest draft", "SUM([Sales])"),
            ("Latest draft", "SUM([Sales]) + 1"),
        ])
        self.assertEqual(dialog.measure, {
            "name": "Latest draft", "expression": "SUM([Sales]) + 1",
        })
        self.assertEqual(
            dialog.preview_label.text(), "Current report-context result: Current result: 42"
        )
        dialog.deleteLater()
        self.app.processEvents()

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
        dialog.show()
        self.app.processEvents()

        # Exercise the editable picker as a user would: type a function name,
        # inspect the filtered completion, and click the matching suggestion.
        function_picker = dialog.function_combo
        function_picker.setFocus()
        function_picker.lineEdit().clear()
        QTest.keyClicks(function_picker.lineEdit(), "NOBLANKROW")
        self.app.processEvents()
        self.assertEqual(function_picker.completer().completionCount(), 1)
        self.assertEqual(
            function_picker.completer().currentCompletion(), "ALLNOBLANKROW"
        )
        completion_popup = function_picker.completer().popup()
        completion_index = function_picker.completer().completionModel().index(0, 0)
        completion_rect = completion_popup.visualRect(completion_index)
        QTest.mouseClick(
            completion_popup.viewport(),
            Qt.MouseButton.LeftButton,
            pos=completion_rect.center(),
        )
        self.app.processEvents()
        self.assertEqual(function_picker.currentText(), "ALLNOBLANKROW")
        self.assertIn("ALLNOBLANKROW", dialog.function_signature_label.text())
        dialog.function_combo.setCurrentText("SUM")
        dialog.insert_function_button.click()
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM([Column])")
        self.assertEqual(dialog.expression_edit.textCursor().selectedText(), "[Column]")
        self.assertIn("SUM([Column])", dialog.function_signature_label.text())
        self.assertIn("Local syntax:", dialog.function_signature_label.text())
        self.assertNotIn("<code>", dialog.function_signature_label.text())
        dialog.expression_edit.clear()
        dialog.function_combo.setCurrentText("COALESCE")
        dialog.insert_function_button.click()
        self.assertEqual(
            dialog.expression_edit.toPlainText(), "COALESCE(expression1, expression2)"
        )
        self.assertEqual(
            dialog.expression_edit.textCursor().selectedText(), "expression1"
        )
        for parser_form in ("BLANK", "DISTINCT", "FALSE", "TRUE"):
            self.assertIn(parser_form, DAX_FUNCTION_NAMES)

        dialog.expression_edit.clear()
        dialog.function_combo.setCurrentText("SUM")
        dialog.insert_function_button.click()
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

    def test_maxx_minx_templates_match_local_function_catalog(self) -> None:
        self.assertIn("MAXX", DAX_FUNCTION_NAMES)
        self.assertIn("MINX", DAX_FUNCTION_NAMES)
        self.assertEqual(set(DAX_FUNCTION_TEMPLATES), set(DAX_FUNCTION_NAMES))
        self.assertEqual(
            DAX_FUNCTION_TEMPLATES["MAXX"],
            ("MAXX('Table', row_expression)", "'Table'"),
        )
        self.assertEqual(
            DAX_FUNCTION_TEMPLATES["MINX"],
            ("MINX('Table', row_expression)", "'Table'"),
        )

    def test_maxx_minx_are_searchable_and_insert_their_table_argument(self) -> None:
        dialog = MeasureDialog(["Sales"], [])
        dialog.show()
        self.app.processEvents()

        for function in ("MAXX", "MINX"):
            dialog.expression_edit.clear()
            picker = dialog.function_combo
            picker.setFocus()
            picker.lineEdit().clear()
            QTest.keyClicks(picker.lineEdit(), function)
            self.app.processEvents()
            self.assertEqual(picker.completer().completionCount(), 1)
            self.assertEqual(picker.completer().currentCompletion(), function)

            popup = picker.completer().popup()
            completion_index = picker.completer().completionModel().index(0, 0)
            QTest.mouseClick(
                popup.viewport(), Qt.MouseButton.LeftButton,
                pos=popup.visualRect(completion_index).center(),
            )
            self.app.processEvents()
            dialog.insert_function_button.click()

            template, selected_argument = DAX_FUNCTION_TEMPLATES[function]
            self.assertEqual(dialog.expression_edit.toPlainText(), template)
            self.assertEqual(
                dialog.expression_edit.textCursor().selectedText(), selected_argument
            )

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()

    def test_maxx_minx_inline_hints_follow_nested_row_expression_arguments(self) -> None:
        dialog = MeasureDialog(["Sales"], [])
        dialog.show()
        self.app.processEvents()

        dialog.expression_edit.setPlainText("MAXX('Sales', ")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertIn("MAXX · argument 2 of 2", dialog.inline_help_label.text())
        self.assertIn("row_expression", dialog.inline_help_label.text())

        dialog.expression_edit.setPlainText("MINX('Sales', MAXX('Orders', ")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertIn("MAXX · argument 2 of 2", dialog.inline_help_label.text())
        self.assertIn("row_expression", dialog.inline_help_label.text())
        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()

    def test_maxx_minx_scope_help_is_accessible_and_measure_only(self) -> None:
        dialog = MeasureDialog(["Sales"], [])
        scope_help = dialog.findChild(QWidget, "daxLocalScopeHelp")
        self.assertIsNotNone(scope_help)
        assert scope_help is not None
        visible_text = scope_help.property("text") or scope_help.toolTip()
        accessible_text = scope_help.accessibleDescription()
        combined = f"{visible_text} {accessible_text}".casefold()
        for expected in (
            "local dax measure form only",
            "loaded table",
            "supported all",
            "allnoblankrow",
            "allselected",
            "numeric or blank",
            "variant",
            "text",
            "date",
            "boolean",
            "arbitrary table",
            "calculated-column",
        ):
            self.assertIn(expected, combined)
        self.assertTrue(scope_help.accessibleName())

        quick_dialog = MeasureDialog(["Sales"], [], quick=True)
        self.assertIsNone(quick_dialog.findChild(QWidget, "daxLocalScopeHelp"))
        dialog.deleteLater()
        quick_dialog.deleteLater()
        self.app.processEvents()

    def test_maxx_measure_dialog_previews_a_loaded_table_row_expression(self) -> None:
        controller = self.populated_controller()
        dialog = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=controller._preview_measure_expression,
        )
        dialog.name_edit.setText("Largest sale")
        dialog.expression_edit.setPlainText("MAXX('VAT sample', [Sales])")
        dialog.preview_button.click()
        self.assertEqual(
            dialog.preview_label.text(), "Current report-context result: 200"
        )
        self.assertNotIn("Largest sale", controller.reportKpis)
        dialog.deleteLater()
        self.app.processEvents()

    def test_maxx_dialog_rejects_invalid_type_in_preview_and_save(self) -> None:
        controller = self.populated_controller()
        dialog = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=controller._preview_measure_expression,
        )
        dialog.name_edit.setText("Highest emirate")
        dialog.expression_edit.setPlainText("MAXX('VAT sample', [Emirates])")

        dialog.preview_button.click()

        self.assertIn("numeric result", dialog.preview_label.text())
        self.assertNotIn("Highest emirate", controller.reportKpis)
        dialog.save_button.click()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog.measure)
        self.assertFalse(any(
            measure["name"] == "Highest emirate" for measure in controller.modelMeasures
        ))
        dialog.deleteLater()
        self.app.processEvents()

    def test_maxx_minx_measure_can_be_edited_and_saved(self) -> None:
        controller = self.populated_controller()
        self.assertTrue(controller.create_measure(
            "Extreme sale", "MAXX('VAT sample', [Sales])"
        ))

        def accept_minx(dialog: MeasureDialog) -> int:
            self.assertEqual(
                dialog.expression_edit.toPlainText(), "MAXX('VAT sample', [Sales])"
            )
            dialog.expression_edit.setPlainText("MINX('VAT sample', [Sales])")
            dialog.preview_button.click()
            self.assertEqual(
                dialog.preview_label.text(), "Current report-context result: 50"
            )
            dialog.save_button.click()
            return dialog.result()

        with patch.object(MeasureDialog, "exec", new=accept_minx):
            self.assertTrue(controller.editMeasure("Extreme sale"))

        updated = next(
            measure for measure in controller.modelMeasures
            if measure["name"] == "Extreme sale"
        )
        self.assertEqual(updated["expression"], "MINX('VAT sample', [Sales])")
        self.assertEqual(updated["value"], "50")

    def test_measure_editor_inline_completion_and_nested_argument_help(self) -> None:
        dialog = MeasureDialog(["Sales"], [])
        dialog.show()
        self.app.processEvents()
        dialog.expression_edit.setPlainText("SUM")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertTrue(dialog.inline_function_suggestions.isVisible())
        self.assertIn(
            "SUM",
            [dialog.inline_function_suggestions.item(index).text()
             for index in range(dialog.inline_function_suggestions.count())],
        )
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM")

        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.app.processEvents()
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM([Column])")
        self.assertEqual(dialog.expression_edit.textCursor().selectedText(), "[Column]")

        dialog.expression_edit.setPlainText("SUM")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertGreaterEqual(dialog.inline_function_suggestions.count(), 2)
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Down)
        selected_function = str(
            dialog.inline_function_suggestions.currentItem().data(
                Qt.ItemDataRole.UserRole
            )
        )
        self.assertEqual(dialog.inline_function_suggestions.currentRow(), 1)
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Return)
        expected_template = DAX_FUNCTION_TEMPLATES[selected_function][0]
        self.assertEqual(dialog.expression_edit.toPlainText(), expected_template)

        dialog.expression_edit.setPlainText("IF")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        original_draft = dialog.expression_edit.toPlainText()
        self.assertTrue(dialog.inline_function_suggestions.isVisible())
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog.inline_function_suggestions.isVisible())
        self.assertEqual(dialog.expression_edit.toPlainText(), original_draft)

        dialog.expression_edit.setPlainText(
            "CALCULATE(SUM([Sales]), IF(TRUE(), 1,"
        )
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertIn("IF · argument 3 of 3", dialog.inline_help_label.text())
        self.assertIn("value_if_false", dialog.inline_help_label.text())

        dialog.expression_edit.setPlainText('SUMX("AVERAGE')
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertFalse(dialog.inline_function_suggestions.isVisible())
        self.assertIn("pause inside text strings", dialog.inline_help_label.text())

        dialog.expression_edit.setPlainText("'Sales'[SUMX")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertFalse(dialog.inline_function_suggestions.isVisible())
        self.assertIn("column", dialog.inline_help_label.text().casefold())
        dialog.deleteLater()
        self.app.processEvents()

    def test_measure_editor_completes_loaded_fields_and_saved_measures(self) -> None:
        dialog = MeasureDialog(
            ["Net Sales", "Sales Amount"],
            [],
            field_references=[
                ("VAT 5%[Net Sales]", "'VAT 5%'[Net Sales]"),
                ("VAT 5%[Sales Amount]", "'VAT 5%'[Sales Amount]"),
                ("VAT 5%[Vendor's Net Sales]", "'VAT 5%'[Vendor's Net Sales]"),
                ("Other[Net Sales]", "'Other'[Net Sales]"),
                ("O'Brien Data[Net Value]", "'O''Brien Data'[Net Value]"),
                ("O'Brien Data[Vendor's Net Sales]", "'O''Brien Data'[Vendor's Net Sales]"),
                ("O'Brien Dept[Net Value]", "'O''Brien Dept'[Net Value]"),
            ],
            measure_references=["Net Sales", "Net Sales Budget"],
            home_table_name="VAT 5%",
        )
        dialog.show()
        self.app.processEvents()

        # A column-argument function offers only fields from the measure's
        # home table, then completes the unqualified DAX column reference.
        expression = "SUM([Net])"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Net") + 3)
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        suggestions = dialog.inline_function_suggestions
        self.assertTrue(suggestions.isVisible())
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Net Sales"],
        )
        self.assertEqual(
            str(suggestions.item(0).data(Qt.ItemDataRole.UserRole + 1)),
            "column",
        )
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM([Net Sales])")
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            "SUM([Net Sales])".index(")"),
        )
        self.assertFalse(suggestions.isVisible())

        # Table-name completion makes the qualified field picker discoverable
        # even when the formula starts with an escaped quoted table name.
        dialog.expression_edit.setPlainText("'O''Brien Da")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["O'Brien Data"],
        )
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.assertEqual(
            dialog.expression_edit.toPlainText(), "'O''Brien Data'"
        )
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            len("'O''Brien Data'"),
        )
        self.assertFalse(suggestions.isVisible())

        # Apostrophes inside bracketed column names are reference content,
        # both in the home table and in a table-qualified reference.
        expression = "SUM([Vendor's Net)"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index(")"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Vendor's Net Sales"],
        )
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.assertEqual(
            dialog.expression_edit.toPlainText(), "SUM([Vendor's Net Sales])"
        )
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            "SUM([Vendor's Net Sales])".index(")"),
        )
        self.assertFalse(suggestions.isVisible())

        expression = "SUM('O''Brien Data'[Vendor's N])"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Vendor's N") + len("Vendor's N"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Vendor's Net Sales"],
        )
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Enter)
        qualified_expected = "SUM('O''Brien Data'[Vendor's Net Sales])"
        self.assertEqual(dialog.expression_edit.toPlainText(), qualified_expected)
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            qualified_expected.index(")"),
        )
        self.assertFalse(suggestions.isVisible())

        # Once an apostrophe-containing column reference is closed, it must
        # not poison lexical state or suppress later function completion.
        expression = "SUM([Vendor's Net Sales]) + AVER"
        dialog.expression_edit.setPlainText(expression)
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertTrue(suggestions.isVisible())
        self.assertIn(
            "AVERAGE",
            [suggestions.item(index).text() for index in range(suggestions.count())],
        )

        # A quoted table name with an escaped apostrophe narrows field matches;
        # clicking a row must preserve the suffix after the reference.
        expression = "SUM('O''Brien Data'[Net]) + 1"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("[Net") + len("[Net"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Net Value"],
        )
        item_rect = suggestions.visualItemRect(suggestions.item(0))
        QTest.mouseClick(
            suggestions.viewport(), Qt.MouseButton.LeftButton,
            pos=item_rect.center(),
        )
        self.app.processEvents()
        self.assertEqual(
            dialog.expression_edit.toPlainText(),
            "SUM('O''Brien Data'[Net Value]) + 1",
        )
        qualified_expected = "SUM('O''Brien Data'[Net Value]) + 1"
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            qualified_expected.index(")"),
        )
        self.assertFalse(suggestions.isVisible())

        # When multiple table names match, mouse acceptance preserves the
        # qualifier suffix and positions the caret after the existing quote.
        expression = "SUM('O''Brien D'[Net Value]) + 1"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("O''Brien D") + len("O''Brien D"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["O'Brien Data", "O'Brien Dept"],
        )
        second_row = suggestions.visualItemRect(suggestions.item(1))
        QTest.mouseClick(
            suggestions.viewport(), Qt.MouseButton.LeftButton,
            pos=second_row.center(),
        )
        self.app.processEvents()
        table_expected = "SUM('O''Brien Dept'[Net Value]) + 1"
        self.assertEqual(dialog.expression_edit.toPlainText(), table_expected)
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            table_expected.index("[Net Value]"),
        )
        self.assertFalse(suggestions.isVisible())

        # Scalar expression references offer saved measures, not columns.
        expression = "CALCULATE([Net S])"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Net") + len("Net S"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Net Sales", "Net Sales Budget"],
        )
        self.assertEqual(
            str(suggestions.item(0).data(Qt.ItemDataRole.UserRole + 1)),
            "measure",
        )
        original = dialog.expression_edit.toPlainText()
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Escape)
        self.app.processEvents()
        self.assertFalse(suggestions.isVisible())
        self.assertEqual(dialog.expression_edit.toPlainText(), original)

        # Enter accepts a saved measure and advances over the existing
        # bracket without reopening the popup.
        expression = "CALCULATE([Net S])"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Net S") + len("Net S"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Return)
        measure_expected = "CALCULATE([Net Sales])"
        self.assertEqual(dialog.expression_edit.toPlainText(), measure_expected)
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            measure_expected.index(")"),
        )
        self.assertFalse(suggestions.isVisible())

        expression = "CALCULATE([Net S]) + 1"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Net S") + len("Net S"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Net Sales", "Net Sales Budget"],
        )
        second_measure = suggestions.visualItemRect(suggestions.item(1))
        QTest.mouseClick(
            suggestions.viewport(), Qt.MouseButton.LeftButton,
            pos=second_measure.center(),
        )
        self.app.processEvents()
        measure_click_expected = "CALCULATE([Net Sales Budget]) + 1"
        self.assertEqual(
            dialog.expression_edit.toPlainText(), measure_click_expected
        )
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            measure_click_expected.index(")"),
        )
        self.assertFalse(suggestions.isVisible())

        # Strings and a caret after a completed reference never show a token
        # popup. Ordinary function completion remains unchanged.
        dialog.expression_edit.setPlainText('SUM("Net S")')
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertFalse(suggestions.isVisible())
        dialog.expression_edit.setPlainText("SUM([Net Sales])")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertFalse(suggestions.isVisible())
        dialog.expression_edit.setPlainText("SUM")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertTrue(suggestions.isVisible())
        self.assertEqual(
            str(suggestions.item(0).data(Qt.ItemDataRole.UserRole + 1)),
            "function",
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_measure_editor_suggests_columns_at_open_aggregation_argument(self) -> None:
        dialog = MeasureDialog(
            ["Net Sales", "Sales Amount"],
            [],
            field_references=[
                ("VAT 5%[Net Sales]", "'VAT 5%'[Net Sales]"),
                ("VAT 5%[Sales Amount]", "'VAT 5%'[Sales Amount]"),
                ("Other[Sales Amount]", "'Other'[Sales Amount]"),
            ],
            home_table_name="VAT 5%",
        )
        dialog.show()
        self.app.processEvents()
        suggestions = dialog.inline_function_suggestions

        dialog.expression_edit.setPlainText("SUM(")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertTrue(suggestions.isVisible())
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Net Sales", "Sales Amount"],
        )
        self.assertEqual(
            str(suggestions.item(0).data(Qt.ItemDataRole.UserRole + 1)),
            "column",
        )
        self.assertIn("SUM([Column])", dialog.function_signature_label.text())
        self.assertIn("Local syntax:", dialog.function_signature_label.text())
        self.assertNotIn("<code>", dialog.function_signature_label.text())
        self.assertGreaterEqual(dialog.function_signature_label.minimumHeight(), 32)
        self.assertIn("argument 1 of 1", dialog.inline_help_label.text())
        self.assertIn("home table", dialog.inline_help_label.text())
        self.assertEqual(dialog.function_combo.currentText(), "")

        expression = "SUM(UNSUPPORTED([Sa]))"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Sa") + len("Sa"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertFalse(suggestions.isVisible())
        self.assertIn(
            "Choose a function or place the caret",
            dialog.function_signature_label.text(),
        )
        self.assertNotIn("SUM · argument", dialog.inline_help_label.text())

        expression = "SUM(Sa)"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index(")"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertEqual(
            [suggestions.item(index).text() for index in range(suggestions.count())],
            ["Sales Amount"],
        )
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.assertEqual(
            dialog.expression_edit.toPlainText(), "SUM([Sales Amount])"
        )
        self.assertEqual(
            dialog.expression_edit.textCursor().position(),
            "SUM([Sales Amount])".index(")"),
        )

        dialog.expression_edit.setPlainText("COUNTROWS(")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertFalse(suggestions.isVisible())
        self.assertIn("COUNTROWS", dialog.inline_help_label.text())

        expression = "SUM((Sales))"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Sales") + len("Sales"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()
        self.assertFalse(suggestions.isVisible())

        expression = "SUM([Net Sales]) / COUNTROWS()"
        dialog.expression_edit.setPlainText(expression)
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertFalse(suggestions.isVisible())
        self.assertIn(
            "Choose a function or place the caret",
            dialog.function_signature_label.text(),
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_completed_home_table_field_previews_with_the_expected_result(self) -> None:
        controller = self.populated_controller()
        home_table = controller._table_catalog[0]
        dialog = MeasureDialog(
            list(controller.headers),
            [],
            home_table_id=str(home_table["id"]),
            home_table_name=str(home_table["name"]),
            field_references=controller._dax_field_references(),
            preview_callback=lambda name, expression: controller._preview_measure_expression(
                name, expression, home_table_id=str(home_table["id"])
            ),
        )
        dialog.show()
        self.app.processEvents()
        dialog.name_edit.setText("Completed sales")
        expression = "SUM([Sa])"
        dialog.expression_edit.setPlainText(expression)
        cursor = dialog.expression_edit.textCursor()
        cursor.setPosition(expression.index("Sa") + len("Sa"))
        dialog.expression_edit.setTextCursor(cursor)
        dialog._refresh_inline_editor_help()

        self.assertEqual(
            [dialog.inline_function_suggestions.item(index).text()
             for index in range(dialog.inline_function_suggestions.count())],
            ["Sales"],
        )
        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Enter)
        self.assertEqual(dialog.expression_edit.toPlainText(), "SUM([Sales])")
        dialog.preview_button.click()
        self.assertEqual(
            dialog.preview_label.text(),
            "Current report-context result: 350.50",
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_countrows_help_explains_optional_home_table_argument(self) -> None:
        dialog = MeasureDialog(["Sales"], [])
        dialog.show()
        self.app.processEvents()

        dialog.function_combo.setCurrentText("COUNTROWS")
        self.assertIn(
            "table argument is optional",
            dialog.function_signature_label.text(),
        )
        self.assertIn(
            "this measure's home table",
            dialog.function_signature_label.text(),
        )

        dialog.expression_edit.setPlainText("COUNTROWS(")
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertIn("table argument is optional", dialog.inline_help_label.text())
        self.assertIn("omit it", dialog.inline_help_label.text())
        self.assertIn("home table", dialog.inline_help_label.text())
        self.assertIn("ALLSELECTED", dialog.inline_help_label.text())

        dialog.deleteLater()
        self.app.processEvents()

    def test_dax_inline_completion_preserves_unicode_before_the_caret(self) -> None:
        dialog = MeasureDialog(["Sales", "Name"], [])
        dialog.show()
        self.app.processEvents()
        expression = 'IF([Name] = "😀", SUM([Sales]), SUM'
        dialog.expression_edit.setPlainText(expression)
        dialog.expression_edit.moveCursor(QTextCursor.MoveOperation.End)
        dialog._refresh_inline_editor_help()
        self.assertTrue(dialog.inline_function_suggestions.isVisible())

        QTest.keyClick(dialog.expression_edit, Qt.Key.Key_Tab)
        self.assertEqual(
            dialog.expression_edit.toPlainText(),
            'IF([Name] = "😀", SUM([Sales]), SUM([Column])',
        )
        self.assertEqual(dialog.expression_edit.textCursor().selectedText(), "[Column]")
        dialog.deleteLater()
        self.app.processEvents()

    def test_distinct_count_without_blank_editor_preview_and_create_flow(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Value\nA\nA\nB", name="DAX values")
        ))
        preview_calls = []

        def preview(name: str, expression: str) -> str:
            preview_calls.append((name, expression))
            return controller._preview_measure_expression(name, expression)

        dialog = MeasureDialog(
            list(controller.headers), [],
            field_references=controller._dax_field_references(),
            preview_callback=preview,
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
        latest_expression = "DISTINCTCOUNT('DAX values'[Value])"
        dialog.expression_edit.setPlainText(latest_expression)
        dialog.save_button.click()
        self.assertEqual(dialog.measure, {
            "name": "Unique values without blank",
            "expression": latest_expression,
        })
        self.assertEqual(preview_calls, [
            (
                "Unique values without blank",
                "DISTINCTCOUNTNOBLANK('DAX values'[Value])",
            ),
            ("Unique values without blank", latest_expression),
        ])
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
        # Power BI drops the trailing space of " ", so it joins the empty text: only "" and "0" remain
        # (verified live: DISTINCTCOUNT 2, DISTINCTCOUNTNOBLANK 2, COUNTBLANK 3 for this column).
        self.assertEqual(controller.reportKpis["Distinct values"], "2")
        self.assertEqual(controller.reportKpis["Distinct values without blank"], "2")
        self.assertEqual(controller.reportKpis["No matching values"], "—")

        controller.add_visual("card", "Distinct blank card", 20, 20, 150, 90)
        controller.add_field_to_well(
            "Fields", "__dax_measure__:Distinct values"
        )
        self.assertEqual(
            controller.visualCardData("Distinct blank card")["value"], "2"
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
        self.assertEqual(reopened.reportKpis["Distinct values"], "2")
        self.assertEqual(reopened.reportKpis["Distinct values without blank"], "2")
        self.assertEqual(reopened.reportKpis["No matching values"], "—")
        self.assertEqual(
            reopened.visualCardData("Distinct blank card")["value"], "2"
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
        self.assertTrue(dialog.content_scroll_area.widgetResizable())
        self.assertIn("supported local DAX subset", dialog.function_help_label.text())

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
