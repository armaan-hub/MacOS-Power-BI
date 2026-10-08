"""Acceptance checks for saved-query load-to-model settings."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.query_engine import append_candidates

QQuickStyle.setStyle("Basic")


class QueryLoadSettingLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.left_path = self.root / "north.csv"
        self.right_path = self.root / "south.csv"
        self.left_path.write_text("id,amount\nN1,10\n", encoding="utf-8")
        self.right_path.write_text("id,amount\nS1,20\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def load_checkbox_state(self, controller: StudioController) -> bool:
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "DataView.qml")
        ))
        self.assertFalse(component.isError(), "\n".join(
            error.toString() for error in component.errors()
        ))
        view = component.createWithInitialProperties({"appController": controller})
        self.assertIsNotNone(view, "\n".join(
            error.toString() for error in component.errors()
        ))
        self.app.processEvents()

        def visual_items(item: QQuickItem):
            yield item
            for child in item.childItems():
                yield from visual_items(child)

        states = [
            bool(item.property("checked"))
            for item in visual_items(view)
            if item.property("text") == "Load to model"
            and item.property("checked") is not None
        ]
        view.deleteLater()
        engine.deleteLater()
        self.app.processEvents()
        self.assertEqual(len(states), 1)
        return states[0]

    def add_append_query(self, controller: StudioController) -> str:
        source_ids = []
        for path in (self.left_path, self.right_path):
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_ids.append(controller.activeTableId)
        candidates = [controller._loaded_candidates[source_id] for source_id in source_ids]
        result = append_candidates(candidates)
        self.assertTrue(controller._create_saved_query(
            "Combined", source_ids, result,
            {"operation": "append", "source_ids": source_ids},
            {header: "text" for header in result.headers},
        ))
        return controller.activeTableId

    def test_load_setting_toggles_model_membership_and_persists(self) -> None:
        controller = self.controller("settings.ini")
        query_id = self.add_append_query(controller)
        self.assertIn("Combined", controller.modelTables)
        self.assertTrue(self.load_checkbox_state(controller))

        self.assertTrue(controller.setQueryLoadEnabled(query_id, False))
        catalog_entry = next(
            table for table in controller.tableCatalog
            if table["sourceId"] == query_id
        )
        self.assertFalse(catalog_entry["loaded"])
        self.assertTrue(catalog_entry["evaluated"])
        self.assertFalse(catalog_entry["loadEnabled"])
        self.assertNotIn("Combined", controller.modelTables)
        self.assertIn(query_id, controller._loaded_candidates)
        self.assertFalse(self.load_checkbox_state(controller))

        excluded_path = self.root / "excluded-query.npa"
        self.assertTrue(controller._save_to(excluded_path))
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(excluded_path))
        self.assertNotIn("Combined", reopened.modelTables)
        self.assertIn(query_id, reopened._loaded_candidates)
        self.assertFalse(self.load_checkbox_state(reopened))

        self.assertTrue(reopened.setQueryLoadEnabled(query_id, True))
        self.assertIn("Combined", reopened.modelTables)
        self.assertTrue(self.load_checkbox_state(reopened))
        enabled_path = self.root / "enabled-query.npa"
        self.assertTrue(reopened._save_to(enabled_path))
        reopened_again = self.controller("enabled-settings.ini")
        self.assertTrue(reopened_again.open_project_path(enabled_path))
        self.assertIn("Combined", reopened_again.modelTables)
        self.assertTrue(self.load_checkbox_state(reopened_again))


if __name__ == "__main__":
    unittest.main()
