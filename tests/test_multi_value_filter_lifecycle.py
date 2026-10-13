"""Acceptance checks for multi-value page and visual filters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController, _encode_report_filter_value
from analytics_studio.file_import import parse_file


class MultiValueFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def table_id(controller: StudioController, source_name: str) -> str:
        source_id = next(
            source["id"] for source in controller._project["data_sources"]
            if source["name"] == source_name
        )
        return next(
            table["id"] for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    def test_text_any_none_blank_search_visual_scope_and_refresh(self) -> None:
        source_path = self.root / "Regions.csv"
        source_path.write_text(
            "Region,Revenue\nEast,10\nWest,20\nNorth,30\n,40\nEast,5\n",
            encoding="utf-8",
        )
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        table_id = self.table_id(controller, source_path.name)

        values = controller.pageFilterValues(table_id, "Region")
        self.assertIn({"label": "(Empty text)", "value": "__npa_pqv1__:empty"}, values)
        self.assertEqual(
            controller.searchPageFilterValues(table_id, "Region", "est"),
            [{"label": "West", "value": _encode_report_filter_value("West")}],
        )
        self.assertEqual(
            controller.searchPageFilterValues(table_id, "Region", "(empty text)"),
            [{"label": "(Empty text)", "value": "__npa_pqv1__:empty"}],
        )

        selected_json = json.dumps(["East", "North", ""])
        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Region", "is_any_of", selected_json
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "85")

        visual_name = "Revenue KPI"
        controller.add_visual("card", visual_name, 14, 14, 120, 80)
        controller.selectVisual(visual_name)
        self.assertTrue(controller.addVisualMultiValueFilter(
            visual_name, table_id, "Region", "is_none_of", json.dumps(["North", ""])
        ))
        self.assertEqual(controller.visualKpis[visual_name], "15")
        self.assertEqual(controller.reportKpis["Revenue"], "85")
        self.assertEqual(len(controller.activePageFilters), 1)
        self.assertEqual(len(controller.activeVisualFilters), 1)

        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Region", "is_none_of", json.dumps(["East", ""])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "50")
        self.assertEqual(controller.visualKpis[visual_name], "20")

        project_path = self.root / "multi-value-filters.npa"
        self.assertTrue(controller._save_to(project_path))
        source_path.write_text(
            "Region,Revenue\nEast,12\nWest,18\nNorth,22\n,25\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Revenue"], "40")
        self.assertEqual(len(reopened.activePageFilters), 1)
        reopened.selectVisual(visual_name)
        self.assertEqual(reopened.visualKpis[visual_name], "18")
        self.assertEqual(len(reopened.activeVisualFilters), 1)

    def test_typed_numeric_values_and_selection_limits(self) -> None:
        source_path = self.root / "Scores.csv"
        source_path.write_text(
            "Region,Score,Revenue,Enabled\n"
            "East,1,10,true\nWest,2,20,true\nNorth,3,30,true\n"
            ",4,40,false\nEast,5,5,false\n",
            encoding="utf-8",
        )
        controller = self.controller("numeric-settings.ini")
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        table_id = self.table_id(controller, source_path.name)
        self.assertTrue(controller.setColumnType("Score", "whole_number"))

        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Score", "is_any_of", json.dumps(["2", "4"])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "60")
        self.assertFalse(controller.addPageMultiValueFilter(
            table_id, "Score", "is_any_of", "not-json"
        ))
        self.assertEqual(len(controller.activePageFilters), 1)

        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Score", "is_none_of", json.dumps(["2", "4"])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "45")
        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Enabled", "is_any_of", json.dumps(["true"])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "40")
        self.assertFalse(controller.addPageMultiValueFilter(
            table_id, "Region", "is_any_of", json.dumps([str(value) for value in range(1001)])
        ))
        self.assertEqual(len(controller.activePageFilters), 2)

    def test_null_and_empty_text_picker_values_filter_separately(self) -> None:
        source_path = self.root / "typed-regions.json"
        source_path.write_text(
            '[{"Region":null,"Revenue":10},'
            '{"Region":"","Revenue":20},'
            '{"Region":"East","Revenue":30}]',
            encoding="utf-8",
        )
        controller = self.controller("typed-settings.ini")
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        table_id = self.table_id(controller, source_path.name)
        options = controller.pageFilterValues(table_id, "Region")
        null_option = next(option for option in options if option["label"] == "(Null)")
        empty_option = next(option for option in options if option["label"] == "(Empty text)")

        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Region", "is_any_of", json.dumps([null_option["value"]])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "10")
        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Region", "is_any_of", json.dumps([empty_option["value"]])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "20")

    def test_picker_values_keep_numeric_and_text_categories_separate(self) -> None:
        source_path = self.root / "mixed-categories.json"
        source_path.write_text(
            '[{"Category":1,"Revenue":10},'
            '{"Category":"1","Revenue":20},'
            '{"Category":"1 (Number)","Revenue":30}]',
            encoding="utf-8",
        )
        controller = self.controller("mixed-categories-settings.ini")
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        table_id = self.table_id(controller, source_path.name)
        options = controller.pageFilterValues(table_id, "Category")
        labels_by_value = {option["value"]: option["label"] for option in options}
        self.assertEqual(len({option["value"] for option in options}), 3)
        number_value = _encode_report_filter_value(1)
        text_value = _encode_report_filter_value("1")
        self.assertTrue(labels_by_value[number_value].startswith("1 (Number)"))
        self.assertEqual(labels_by_value[text_value], "1 (Text)")
        self.assertEqual(len(set(labels_by_value.values())), 3)

        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Category", "is_any_of", json.dumps([number_value])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "10")
        self.assertEqual(
            controller.activePageFilters[0]["displayValue"],
            "is any of 1 (Number)",
        )
        self.assertTrue(controller.addPageMultiValueFilter(
            table_id, "Category", "is_any_of", json.dumps([text_value])
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "20")
        self.assertEqual(
            controller.activePageFilters[0]["displayValue"],
            "is any of 1 (Text)",
        )


if __name__ == "__main__":
    unittest.main()
