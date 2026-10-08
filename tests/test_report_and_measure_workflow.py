"""Controller integration tests for field-aware reporting and saved measures."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.inline_data import parse_pasted_table
from analytics_studio.measure_dialog import MeasureDialog


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
        self.assertTrue(controller.create_measure("Total Sales", "SUM([Sales])"))
        self.assertTrue(controller.create_measure("Average Sale", "[Total Sales] / COUNTROWS()"))
        self.assertEqual(controller.reportKpis["Total Sales"], "350.50")
        self.assertEqual(controller.modelMeasures[1]["value"], "116.83")
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
        self.assertEqual(controller.reportKpis["Line sales"], "751.50")
        self.assertEqual(controller.reportKpis["Average line sales"], "250.50")

        controller.setRegionFilter("Dubai")
        self.assertEqual(controller.reportKpis["Line sales"], "450")
        self.assertEqual(controller.reportKpis["Average line sales"], "225")
        controller.setRegionFilter("All regions")

        path = self.root / "iterator-measures.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened.reportKpis["Line sales"], "751.50")
        self.assertEqual(reopened.reportKpis["Average line sales"], "250.50")

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


if __name__ == "__main__":
    unittest.main()
