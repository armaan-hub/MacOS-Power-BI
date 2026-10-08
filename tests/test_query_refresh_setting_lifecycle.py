"""Acceptance checks for saved-query report-refresh settings and cache use."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.query_engine import append_candidates

QQuickStyle.setStyle("Basic")


class QueryRefreshSettingLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.left_path = self.root / "north.csv"
        self.right_path = self.root / "south.csv"
        self.peer_path = self.root / "archive.csv"
        self.left_path.write_text("id,amount\nN1,10\n", encoding="utf-8")
        self.right_path.write_text("id,amount\nS1,20\n", encoding="utf-8")
        self.peer_path.write_text("id,amount\nA1,100\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def refresh_checkbox_state(self, controller: StudioController) -> bool:
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
        view.setProperty("width", 1000.0)
        view.setProperty("height", 800.0)
        self.app.processEvents()

        def visual_items(item):
            yield item
            for child in item.childItems():
                yield from visual_items(child)

        states = [
            bool(item.property("checked"))
            for item in visual_items(view)
            if item.property("text") == "Include in refresh"
            and item.property("checked") is not None
        ]
        view.deleteLater()
        engine.deleteLater()
        self.app.processEvents()
        self.assertEqual(len(states), 1)
        return states[0]

    @staticmethod
    def append_query(
        controller: StudioController,
        name: str,
        source_ids: list[str],
    ) -> str:
        candidate = append_candidates([
            controller._loaded_candidates[source_id] for source_id in source_ids
        ])
        definition = {"operation": "append", "source_ids": source_ids}
        if not controller._create_saved_query(
            name, source_ids, candidate, definition,
            {header: "text" for header in candidate.headers},
        ):
            raise AssertionError(controller.statusMessage)
        return controller.activeTableId

    def test_excluded_intermediate_query_keeps_cache_across_refresh(self) -> None:
        controller = self.controller("settings.ini")
        source_ids = []
        for path in (self.left_path, self.right_path, self.peer_path):
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_ids.append(controller.activeTableId)

        intermediate_id = self.append_query(
            controller, "Intermediate", source_ids[:2]
        )
        report_id = self.append_query(
            controller, "Report", [intermediate_id, source_ids[2]]
        )
        self.assertTrue(controller.setQueryRefreshIncluded(intermediate_id, False))
        catalog = {
            table["sourceId"]: table for table in controller.tableCatalog
        }
        self.assertFalse(catalog[intermediate_id]["includeInReportRefresh"])
        self.assertTrue(catalog[report_id]["includeInReportRefresh"])
        self.assertFalse(self.refresh_checkbox_state(controller))

        project_path = self.root / "excluded-refresh-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.left_path.write_text("id,amount\nN1,100\n", encoding="utf-8")
        self.right_path.write_text("id,amount\nS1,200\n", encoding="utf-8")
        self.peer_path.write_text("id,amount\nA1,1000\n", encoding="utf-8")

        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._loaded_candidates[intermediate_id].rows, [
            {"id": "N1", "amount": "100"},
            {"id": "S1", "amount": "200"},
        ])
        self.assertFalse(next(
            table for table in reopened.tableCatalog
            if table["sourceId"] == intermediate_id
        )["includeInReportRefresh"])
        self.assertFalse(self.refresh_checkbox_state(reopened))

        self.left_path.write_text("id,amount\nN1,101\n", encoding="utf-8")
        self.right_path.write_text("id,amount\nS1,201\n", encoding="utf-8")
        self.peer_path.write_text("id,amount\nA1,1001\n", encoding="utf-8")
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[intermediate_id].rows, [
            {"id": "N1", "amount": "100"},
            {"id": "S1", "amount": "200"},
        ])
        self.assertEqual(reopened._loaded_candidates[report_id].rows, [
            {"id": "N1", "amount": "100"},
            {"id": "S1", "amount": "200"},
            {"id": "A1", "amount": "1001"},
        ])


if __name__ == "__main__":
    unittest.main()
