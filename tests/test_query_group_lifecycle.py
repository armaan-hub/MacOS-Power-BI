"""Acceptance checks for query-group assignment and project persistence."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.query_engine import append_candidates

QQuickStyle.setStyle("Basic")


class QueryGroupLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.peer_path = self.root / "archive.csv"
        self.source_path.write_text("id,amount\nA,10\n", encoding="utf-8")
        self.peer_path.write_text("id,amount\nB,20\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def rendered_text(self, controller: StudioController) -> set[str]:
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
        values = {
            str(obj.property("text"))
            for obj in view.findChildren(QObject)
            if obj.metaObject().indexOfProperty("text") >= 0
        }
        view.deleteLater()
        engine.deleteLater()
        self.app.processEvents()
        return values

    def test_group_assignment_move_clear_and_reopen_display(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        source_id = controller.activeTableId
        self.assertTrue(controller._commit_import(
            self.peer_path, parse_file(self.peer_path)
        ))
        peer_id = controller.activeTableId
        self.assertTrue(controller.selectTable(source_id))

        with patch(
            "analytics_studio.controller.QInputDialog.getText",
            return_value=("  Finance  ", True),
        ):
            self.assertTrue(controller.editQueryGroup(source_id))
        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(source["query_group"], "Finance")
        catalog_item = next(
            item for item in controller.tableCatalog
            if item["sourceId"] == source_id
        )
        self.assertEqual(catalog_item["queryGroup"], "Finance")
        self.assertEqual(catalog_item["displayName"], "Finance / sales")
        self.assertIn("Query group · Finance", self.rendered_text(controller))

        append_result = append_candidates([
            controller._loaded_candidates[source_id],
            controller._loaded_candidates[peer_id],
        ])
        self.assertTrue(controller._create_saved_query(
            "Combined sales",
            [source_id, peer_id],
            append_result,
            {"operation": "append", "source_ids": [source_id, peer_id]},
            {"id": "text", "amount": "text"},
        ))
        query_id = controller.activeTableId
        with patch(
            "analytics_studio.controller.QInputDialog.getText",
            return_value=("Operations", True),
        ):
            self.assertTrue(controller.editQueryGroup(query_id))
        query_item = next(
            item for item in controller.tableCatalog if item["sourceId"] == query_id
        )
        self.assertEqual(query_item["queryGroup"], "Operations")
        self.assertIn("Query group · Operations", self.rendered_text(controller))

        project_path = self.root / "groups.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertIn("Query group · Operations", self.rendered_text(reopened))
        self.assertEqual(
            next(item for item in reopened.tableCatalog if item["sourceId"] == source_id)["queryGroup"],
            "Finance",
        )

        with patch(
            "analytics_studio.controller.QInputDialog.getText",
            return_value=("Reporting", True),
        ):
            self.assertTrue(reopened.editQueryGroup(query_id))
        moved = next(
            item for item in reopened.tableCatalog if item["sourceId"] == query_id
        )
        self.assertEqual(moved["queryGroup"], "Reporting")

        with patch(
            "analytics_studio.controller.QInputDialog.getText",
            return_value=("", True),
        ):
            self.assertTrue(reopened.editQueryGroup(query_id))
        cleared = next(
            item for item in reopened.tableCatalog if item["sourceId"] == query_id
        )
        self.assertEqual(cleared["queryGroup"], "")
        self.assertEqual(cleared["displayName"], "Combined sales")


if __name__ == "__main__":
    unittest.main()
