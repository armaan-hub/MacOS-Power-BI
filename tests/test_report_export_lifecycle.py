"""Acceptance checks for report-page PDF rendering and export."""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Q_ARG, QMetaObject, QSettings, Qt, QUrl
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController

QQuickStyle.setStyle("Basic")


class ReportExportLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_qml_exports_visible_pages_and_restores_report_state(self) -> None:
        controller = StudioController(
            self.app,
            QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat),
        )
        controller.add_visual("card", "First page card", 40, 40, 300, 180)
        controller.add_page()
        controller.add_visual("card", "Second page card", 40, 40, 300, 180)
        controller.add_page()
        hidden_page_id = str(controller.pages[2]["id"])
        controller.add_visual("card", "Hidden page card", 40, 40, 300, 180)
        controller.hide_page(hidden_page_id, True)
        controller.setActivePage(1)
        controller.selectVisual("Second page card")
        controller._cross_filters["Second page card"] = ["Selected category"]
        controller._dirty = False

        qml_path = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
        self.assertFalse(
            component.isError(), "\n".join(error.toString() for error in component.errors())
        )
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(
            window, "\n".join(error.toString() for error in component.errors())
        )
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()

        pdf_path = self.root / "presentation.pdf"
        self.assertTrue(QMetaObject.invokeMethod(
            window,
            "beginReportPdfExport",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", str(pdf_path)),
        ))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (
            not pdf_path.exists() or bool(window.property("reportPdfExporting"))
        ):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

        self.assertTrue(pdf_path.is_file(), controller.statusMessage)
        document = pdf_path.read_bytes()
        self.assertTrue(document.startswith(b"%PDF-"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", document)), 2)
        self.assertEqual(controller.activePageIndex, 1)
        self.assertEqual(controller.selectedVisual, "Second page card")
        self.assertEqual(controller._cross_filters, {"Second page card": ["Selected category"]})
        self.assertFalse(controller.dirty)
        self.assertIn("Exported 2 report pages", controller.statusMessage)

        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
