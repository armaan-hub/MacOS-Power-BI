"""Acceptance checks for table-scoped default summarization behavior."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.calculated_column_dialog import CalculatedColumnDialog
from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.inline_data import parse_pasted_table
from analytics_studio.project import validate_project


class ModelColumnSummarizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str = "settings.ini") -> StudioController:
        settings = QSettings(
            str(self.root / name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def load_csv(
        self,
        controller: StudioController,
        contents: str,
        name: str = "Orders.csv",
    ) -> tuple[Path, str]:
        path = self.root / name
        path.write_text(contents, encoding="utf-8")
        self.assertTrue(controller._commit_import(path, parse_file(path)))
        return path, str(controller.activeTableId)

    @staticmethod
    def model_table(
        controller: StudioController, *, table_id: str | None = None
    ) -> dict:
        return next(
            table for table in controller._project["model"]["tables"]
            if table_id is None or table.get("id") == table_id
        )

    @staticmethod
    def catalog_table(
        controller: StudioController, table_id: str
    ) -> dict:
        return next(
            table for table in controller.tableCatalog
            if table.get("id") == table_id
        )

    @staticmethod
    def visual(controller: StudioController, title: str) -> dict:
        return next(
            visual for visual in controller._active_page()["visuals"]
            if visual.get("title") == title
        )

    def set_default(
        self,
        controller: StudioController,
        table_id: str,
        column: str,
        value: str,
    ) -> None:
        self.assertTrue(
            controller.set_column_default_summarization(table_id, column, value),
            controller.statusMessage,
        )

    def add_chart_field(
        self,
        controller: StudioController,
        title: str,
        *,
        visual_type: str = "column",
        well: str = "Y-axis",
        column: str = "Amount",
        category: str = "Region",
    ) -> dict:
        controller.add_visual(visual_type, title, 20, 20, 320, 220)
        if visual_type in {"column", "bar", "line", "lineClusteredColumn"}:
            controller.add_field_to_well("X-axis", category)
        controller.add_field_to_well(well, column)
        return self.visual(controller, title)

    def add_matrix_value(
        self, controller: StudioController, title: str = "Summary matrix"
    ) -> dict:
        controller.add_visual("matrix", title, 20, 20, 320, 220)
        controller.add_field_to_well("Rows", "Region")
        controller.add_field_to_well("Columns", "Period")
        controller.add_field_to_well("Values", "Amount")
        return self.visual(controller, title)

    def save_calculated_column(
        self,
        controller: StudioController,
        name: str,
        expression: str,
    ) -> bool:
        table = self.model_table(controller)
        dialog = CalculatedColumnDialog(table.get("calculated_columns", []))
        dialog.name_edit.setText(name)
        dialog.expression_edit.setPlainText(expression)

        def accept_dialog() -> QDialog.DialogCode:
            dialog._accept_column()
            return dialog.result()

        with (
            patch("analytics_studio.controller.CalculatedColumnDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
            patch("analytics_studio.controller.QMessageBox.warning"),
        ):
            return controller.calculated_column_dialog()

    def test_setter_uses_catalog_id_and_rejects_invalid_fields_transactionally(self) -> None:
        controller = self.controller()
        _path, source_id = self.load_csv(
            controller,
            "Region,Amount,Label\nNorth,2.5,first\nSouth,7.5,second\n",
        )
        original_table = self.model_table(controller)
        catalog_id = "orders-catalog-id"
        original_table["id"] = catalog_id
        controller._project = validate_project(controller._project)
        controller._refresh_model_view()

        self.assertEqual(self.catalog_table(controller, catalog_id)["sourceId"], source_id)
        self.set_default(controller, catalog_id, "Amount", "average")
        self.assertEqual(
            self.model_table(controller, table_id=catalog_id)["column_summarizations"],
            {"Amount": "average"},
        )
        self.assertFalse(
            controller.set_column_default_summarization(source_id, "Amount", "count")
        )

        self.assertTrue(self.save_calculated_column(controller, "Calculated", "[Amount] * 2"))
        before_project = deepcopy(controller._project)
        before_dirty = controller.dirty
        rejected = (
            ("missing-table-id", "Amount", "sum"),
            (catalog_id, "Removed field", "sum"),
            (catalog_id, "Label", "sum"),
            (catalog_id, "Calculated", "count"),
            (catalog_id, "Amount", "median"),
        )
        for table_id, column, value in rejected:
            with self.subTest(table_id=table_id, column=column, value=value):
                self.assertFalse(
                    controller.set_column_default_summarization(
                        table_id, column, value
                    )
                )
                self.assertEqual(controller._project, before_project)
                self.assertEqual(controller.dirty, before_dirty)

    def test_same_named_columns_in_different_tables_keep_independent_defaults(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(parse_pasted_table(
            "Region,Amount\nNorth,2\nSouth,3\n", name="First orders"
        )))
        first_source_id = str(controller.activeTableId)
        first_table = self.catalog_table(controller, first_source_id)

        self.assertTrue(controller._commit_inline(parse_pasted_table(
            "Region,Amount\nNorth,10\nSouth,20\n", name="Second orders"
        )))
        second_source_id = str(controller.activeTableId)
        second_table = self.catalog_table(controller, second_source_id)
        self.assertNotEqual(first_table["id"], second_table["id"])

        self.set_default(controller, first_table["id"], "Amount", "sum")
        self.set_default(controller, second_table["id"], "Amount", "count")

        self.assertEqual(
            self.model_table(controller, table_id=first_table["id"])[
                "column_summarizations"
            ],
            {"Amount": "sum"},
        )
        self.assertEqual(
            self.model_table(controller, table_id=second_table["id"])[
                "column_summarizations"
            ],
            {"Amount": "count"},
        )
        self.assertTrue(controller.selectTable(first_source_id))
        first_visual = self.add_chart_field(controller, "First table chart")
        self.assertEqual(first_visual["table_id"], first_table["id"])
        self.assertEqual(first_visual["field_aggregations"]["Amount"], "sum")
        self.assertTrue(controller.selectTable(second_source_id))
        second_visual = self.add_chart_field(controller, "Second table chart")
        self.assertEqual(second_visual["table_id"], second_table["id"])
        self.assertEqual(second_visual["field_aggregations"]["Amount"], "count")

    def test_supported_value_wells_apply_sum_average_and_count_with_results(self) -> None:
        controller = self.controller()
        _path, table_id = self.load_csv(
            controller,
            "Region,Period,Amount\nNorth,Q1,2\nNorth,Q1,4\nSouth,Q2,6\n",
        )
        assignments = (
            ("column", "Y-axis", "average", "Chart average"),
            ("lineClusteredColumn", "Column Y-axis", "count", "Combo column count"),
            ("lineClusteredColumn", "Line Y-axis", "sum", "Combo line sum"),
            ("gauge", "Value", "average", "Gauge value average"),
            ("gauge", "Minimum", "count", "Gauge minimum count"),
            ("gauge", "Maximum", "sum", "Gauge maximum sum"),
            ("gauge", "Target", "average", "Gauge target average"),
            ("card", "Fields", "count", "Card count"),
            ("matrix", "Values", "average", "Matrix average"),
        )
        for visual_type, well, aggregation, title in assignments:
            self.set_default(controller, table_id, "Amount", aggregation)
            if visual_type == "matrix":
                visual = self.add_matrix_value(controller, title)
            else:
                visual = self.add_chart_field(
                    controller,
                    title,
                    visual_type=visual_type,
                    well=well,
                )
                if visual_type == "gauge" and well != "Value":
                    controller.add_field_to_well("Value", "Amount")
            with self.subTest(visual_type=visual_type, well=well):
                self.assertEqual(
                    visual["field_aggregations"]["Amount"], aggregation
                )

        self.assertEqual(
            controller.visualSeries("Chart average"),
            [
                {"label": "North", "value": 3.0},
                {"label": "South", "value": 6.0},
            ],
        )
        self.assertEqual(
            controller.visualSeries("Combo column count"),
            [
                {"label": "North", "value": 2.0},
                {"label": "South", "value": 1.0},
            ],
        )
        self.assertEqual(
            controller.visualLineSeries("Combo line sum"),
            [
                {"label": "North", "value": 6.0},
                {"label": "South", "value": 6.0},
            ],
        )
        self.assertEqual(controller.visualGaugeData("Gauge value average")["value"], 4.0)
        self.assertEqual(controller.visualGaugeData("Gauge minimum count")["minimum"], 3.0)
        self.assertEqual(controller.visualGaugeData("Gauge maximum sum")["maximum"], 12.0)
        self.assertEqual(controller.visualGaugeData("Gauge target average")["target"], 4.0)
        self.assertEqual(controller.visualCardData("Card count")["value"], "3")
        self.assertEqual(controller.visualCardData("Card count")["aggregation"], "Count")
        matrix = controller.visualMatrixData("Matrix average")
        self.assertEqual(matrix["rows"][0]["values"], ["North", "3", ""])

    def test_model_default_applies_to_every_non_scatter_y_axis_visual(self) -> None:
        controller = self.controller()
        _path, table_id = self.load_csv(
            controller,
            "Region,Amount\nNorth,2\nSouth,4\n",
        )
        self.set_default(controller, table_id, "Amount", "average")
        visual_types = (
            "waterfall", "treemap", "column", "bar", "stackedBar",
            "stackedColumn", "bar100", "column100", "stackedArea",
            "area100", "line", "area", "pie", "donut", "funnel", "ribbon",
        )

        for index, visual_type in enumerate(visual_types):
            title = f"Y-axis default {index}"
            controller.add_visual(visual_type, title, 20, 20, 320, 220)
            with self.subTest(visual_type=visual_type):
                self.assertIn(
                    "Y-axis",
                    {str(item["name"]) for item in controller.activeVisualWells},
                )
                controller.add_field_to_well("Y-axis", "Amount")
                visual = self.visual(controller, title)
                self.assertEqual(
                    visual["field_aggregations"]["Amount"], "average"
                )

    def test_explicit_auto_matches_missing_metadata_fallback_in_each_supported_well(self) -> None:
        path = self.root / "Auto.csv"
        path.write_text(
            "Region,Period,Amount\nNorth,Q1,2\nNorth,Q1,4\nSouth,Q2,6\n",
            encoding="utf-8",
        )
        for visual_type, well in (
            ("column", "Y-axis"),
            ("lineClusteredColumn", "Column Y-axis"),
            ("lineClusteredColumn", "Line Y-axis"),
            ("gauge", "Value"),
            ("gauge", "Minimum"),
            ("gauge", "Maximum"),
            ("gauge", "Target"),
            ("card", "Fields"),
            ("matrix", "Values"),
        ):
            auto_controller = self.controller(f"auto-{visual_type}-{well}.ini")
            missing_controller = self.controller(f"missing-{visual_type}-{well}.ini")
            self.assertTrue(auto_controller._commit_import(path, parse_file(path)))
            self.assertTrue(missing_controller._commit_import(path, parse_file(path)))
            table_id = str(auto_controller.tableCatalog[0]["id"])
            self.set_default(auto_controller, table_id, "Amount", "auto")

            if visual_type == "matrix":
                auto_visual = self.add_matrix_value(auto_controller, "Auto")
                missing_visual = self.add_matrix_value(missing_controller, "Missing")
            else:
                auto_visual = self.add_chart_field(
                    auto_controller, "Auto", visual_type=visual_type, well=well
                )
                missing_visual = self.add_chart_field(
                    missing_controller, "Missing", visual_type=visual_type, well=well
                )

            with self.subTest(visual_type=visual_type, well=well):
                self.assertEqual(
                    auto_visual["field_aggregations"]["Amount"], "sum"
                )
                self.assertEqual(
                    auto_visual["field_aggregations"],
                    missing_visual["field_aggregations"],
                )
                self.assertEqual(
                    auto_controller.visualFieldAggregation(well, "Amount"),
                    missing_controller.visualFieldAggregation(well, "Amount"),
                )

    def test_unsupported_wells_and_kpi_keep_their_existing_fallback(self) -> None:
        controller = self.controller()
        _path, table_id = self.load_csv(
            controller,
            "Region,Period,Amount\nNorth,Q1,2\nSouth,Q2,4\n",
        )
        self.set_default(controller, table_id, "Amount", "count")

        controller.add_visual("column", "Category only", 20, 20, 300, 200)
        for well in ("X-axis", "Legend", "Tooltips"):
            controller.add_field_to_well(well, "Amount")
        self.assertNotIn("Amount", self.visual(controller, "Category only").get("field_aggregations", {}))

        controller.add_visual("matrix", "Matrix groups", 340, 20, 300, 200)
        controller.add_field_to_well("Rows", "Amount")
        controller.add_field_to_well("Columns", "Period")
        self.assertNotIn("Amount", self.visual(controller, "Matrix groups").get("field_aggregations", {}))

        controller.add_visual("table", "Detail table", 660, 20, 300, 200)
        controller.add_field_to_well("Fields", "Amount")
        self.assertNotIn("Amount", self.visual(controller, "Detail table").get("field_aggregations", {}))

        controller.add_visual("scatter", "Scatter", 20, 260, 300, 200)
        for well in ("X-axis", "Y-axis", "Legend", "Details", "Tooltips"):
            controller.add_field_to_well(well, "Amount")
        self.assertNotIn("Amount", self.visual(controller, "Scatter").get("field_aggregations", {}))

        controller.add_visual("map", "Map", 340, 260, 300, 200)
        controller.add_field_to_well("Size", "Amount")
        self.assertNotIn("Amount", self.visual(controller, "Map").get("field_aggregations", {}))

        controller.add_visual("kpi", "KPI", 660, 260, 300, 200)
        controller.add_field_to_well("Indicator", "Amount")
        self.assertEqual(
            self.visual(controller, "KPI")["field_aggregations"]["Amount"],
            "sum",
        )

    def test_visual_override_is_independent_of_later_model_default_changes(self) -> None:
        controller = self.controller()
        _path, table_id = self.load_csv(
            controller,
            "Region,Amount\nNorth,2\nSouth,4\n",
        )
        self.set_default(controller, table_id, "Amount", "count")
        existing = self.add_chart_field(controller, "Existing override")
        self.assertEqual(existing["field_aggregations"]["Amount"], "count")
        controller.set_field_aggregation("Y-axis", "Amount", "average")

        self.set_default(controller, table_id, "Amount", "sum")

        self.assertEqual(
            self.visual(controller, "Existing override")["field_aggregations"]["Amount"],
            "average",
        )
        new_visual = self.add_chart_field(controller, "New default")
        self.assertEqual(new_visual["field_aggregations"]["Amount"], "sum")

    def test_default_and_visual_aggregation_persist_and_recompute_after_refresh(self) -> None:
        controller = self.controller()
        source_path, table_id = self.load_csv(
            controller,
            "Region,Amount\nNorth,2\nSouth,4\n",
        )
        self.set_default(controller, table_id, "Amount", "average")
        controller.add_visual("card", "Average card", 20, 20, 180, 100)
        controller.add_field_to_well("Fields", "Amount")
        controller.set_field_aggregation("Fields", "Amount", "count")
        self.assertEqual(controller.visualCardData("Average card")["value"], "2")

        project_path = self.root / "summarization.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_table = self.catalog_table(reopened, table_id)
        self.assertEqual(reopened_table["columnSummarizations"], {"Amount": "average"})
        self.assertEqual(reopened.visualCardData("Average card")["aggregation"], "Count")
        self.assertEqual(reopened.visualCardData("Average card")["value"], "2")

        source_path.write_text(
            "Region,Amount\nNorth,10\nSouth,14\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened.visualCardData("Average card")["value"], "2")
        reopened.add_visual("card", "Model average card", 220, 20, 180, 100)
        reopened.add_field_to_well("Fields", "Amount")
        self.assertEqual(reopened.visualCardData("Model average card")["aggregation"], "Average")
        self.assertEqual(reopened.visualCardData("Model average card")["value"], "12")

    def test_removed_source_field_default_is_dormant_then_resumes_on_same_table(self) -> None:
        controller = self.controller()
        source_path, table_id = self.load_csv(
            controller,
            "Region,Amount\nNorth,2\nSouth,4\n",
        )
        self.set_default(controller, table_id, "Amount", "count")

        source_path.write_text("Region\nNorth\nSouth\n", encoding="utf-8")
        controller.refresh_source()
        self.assertEqual(
            self.model_table(controller, table_id=table_id)["column_summarizations"],
            {"Amount": "count"},
        )
        project_path = self.root / "dormant.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("dormant-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            self.catalog_table(reopened, table_id)["columnSummarizations"],
            {"Amount": "count"},
        )

        source_path.write_text(
            "Region,Amount\nNorth,7\nSouth,9\n", encoding="utf-8"
        )
        reopened.refresh_source()
        visual = self.add_chart_field(reopened, "Restored column")
        self.assertEqual(visual["field_aggregations"]["Amount"], "count")
        self.assertEqual(
            reopened.visualSeries("Restored column"),
            [
                {"label": "North", "value": 1.0},
                {"label": "South", "value": 1.0},
            ],
        )

    def test_nonnumeric_and_unavailable_sources_leave_defaults_dormant(self) -> None:
        controller = self.controller()
        source_path, table_id = self.load_csv(
            controller,
            "Region,Amount\nNorth,2\nSouth,4\n",
        )
        self.set_default(controller, table_id, "Amount", "count")
        source_path.write_text(
            "Region,Amount\nNorth,high\nSouth,low\n", encoding="utf-8"
        )
        controller.refresh_source()
        self.assertEqual(
            self.model_table(controller, table_id=table_id)["column_summarizations"],
            {"Amount": "count"},
        )
        self.assertEqual(
            self.catalog_table(controller, table_id)["columnTypes"]["Amount"], "text"
        )
        nonnumeric_visual = self.add_chart_field(controller, "Nonnumeric fallback")
        self.assertEqual(
            nonnumeric_visual["field_aggregations"]["Amount"], "sum"
        )

        project_path = self.root / "unavailable.npa"
        self.assertTrue(controller._save_to(project_path))
        source_path.unlink()
        reopened = self.controller("unavailable-reopened.ini")
        with patch("analytics_studio.controller.QMessageBox.warning"):
            self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            self.catalog_table(reopened, table_id)["columnSummarizations"],
            {"Amount": "count"},
        )
        self.assertFalse(self.catalog_table(reopened, table_id)["loaded"])
        before_project = deepcopy(reopened._project)
        before_dirty = reopened.dirty
        self.assertFalse(
            reopened.set_column_default_summarization(table_id, "Amount", "sum")
        )
        self.assertEqual(reopened._project, before_project)
        self.assertEqual(reopened.dirty, before_dirty)

    def test_dormant_source_default_does_not_attach_to_same_named_calculated_column(self) -> None:
        controller = self.controller()
        source_path, table_id = self.load_csv(
            controller,
            "Region,Quantity,Amount\nNorth,2,10\nSouth,4,12\n",
        )
        self.set_default(controller, table_id, "Amount", "count")

        source_path.write_text(
            "Region,Quantity\nNorth,2\nSouth,4\n", encoding="utf-8"
        )
        controller.refresh_source()
        self.assertTrue(self.save_calculated_column(controller, "Amount", "[Quantity] * 2"))
        self.assertIn("Amount", controller._headers)
        self.assertEqual(
            self.model_table(controller, table_id=table_id)["column_summarizations"],
            {"Amount": "count"},
        )

        visual = self.add_chart_field(controller, "Calculated collision")
        self.assertEqual(visual["field_aggregations"]["Amount"], "sum")
        self.assertEqual(
            controller.visualSeries("Calculated collision"),
            [
                {"label": "North", "value": 4.0},
                {"label": "South", "value": 8.0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
