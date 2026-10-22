"""Acceptance checks for full-table column quality and value distribution."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog

QQuickStyle.setStyle("Basic")


class ColumnProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_profile_counts_all_rows_and_ranks_common_values(self) -> None:
        source = self.root / "profile.csv"
        records = ["Category,Score,Edge,Blank,Ties"]
        records.extend(
            f"A,1,{'Solo' if index == 0 else ''},,{'a' if index == 0 else 'A' if index == 1 else ''}"
            for index in range(300)
        )
        records.extend("B,2,,," for _ in range(200))
        records.append("C,3,,,")
        records.extend(",0,,," for _ in range(3))
        source.write_text("\n".join(records) + "\n", encoding="utf-8")

        settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        controller = StudioController(self.app, settings)
        self.assertTrue(controller._commit_import(source, parse_file(source)))

        category_profile = controller.profileColumn("Category")
        self.assertEqual(category_profile["rowCount"], 504)
        self.assertEqual(category_profile["validCount"], 501)
        self.assertEqual(category_profile["errorCount"], 0)
        self.assertEqual(category_profile["emptyCount"], 3)
        self.assertEqual(category_profile["distinctCount"], 3)
        self.assertEqual(category_profile["uniqueCount"], 1)
        self.assertEqual(category_profile["topValues"], [
            {"value": "A", "count": 300},
            {"value": "B", "count": 200},
            {"value": "C", "count": 1},
        ])

        edge_profile = controller.profileColumn("Edge")
        self.assertEqual(edge_profile["distinctCount"], 1)
        self.assertEqual(edge_profile["uniqueCount"], 1)
        blank_profile = controller.profileColumn("Blank")
        self.assertEqual(blank_profile["distinctCount"], 0)
        self.assertEqual(blank_profile["uniqueCount"], 0)
        # The loaded model stores "a" and "A" as one value under the first spelling (Power BI's VertiPaq);
        # the Power Query dialog below profiles the query's own values, which keep them apart.
        self.assertEqual(controller.profileColumn("Ties")["topValues"], [
            {"value": "a", "count": 2},
        ])

        candidate = controller._query_candidates[controller._active_source_id]  # the Power Query editor profiles query values
        dialog = TransformDataDialog(candidate)
        self.assertEqual(dialog.profile_table.item(2, 2).text(), "1")
        self.assertEqual(dialog.profile_table.item(2, 3).text(), "1")
        self.assertEqual(dialog.profile_table.item(3, 2).text(), "0")
        self.assertEqual(dialog.profile_table.item(3, 3).text(), "0")
        self.assertEqual(dialog.profile_table.item(4, 4).text(), "A (1), a (1)")
        dialog.deleteLater()

        self.assertTrue(controller.setColumnType("Score", "whole_number"))
        score_profile = controller.profileColumn("Score")
        self.assertEqual(score_profile["type"], "whole_number")
        self.assertEqual(score_profile["rowCount"], 504)
        self.assertEqual(score_profile["validCount"], 504)
        self.assertEqual(score_profile["errorCount"], 0)
        self.assertEqual(score_profile["emptyCount"], 0)
        self.assertEqual(score_profile["distinctCount"], 4)

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
        rendered_text = {
            str(obj.property("text"))
            for obj in view.findChildren(QObject)
            if obj.metaObject().indexOfProperty("text") >= 0
        }
        self.assertIn("Profile · Category · all rows", rendered_text)
        self.assertIn("Valid 501 (99%)", rendered_text)
        self.assertIn("Errors 0 (0%)", rendered_text)
        self.assertIn("Empty 3 (1%)", rendered_text)
        self.assertIn("Distinct 3 · unique 1", rendered_text)
        self.assertIn("Top: A (300), B (200), C (1)", rendered_text)
        view.deleteLater()
        engine.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
