"""Acceptance checks for saved page-level exact-value filters."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


class PageFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.source_path.write_text(
            "Date,Region,Revenue\n"
            "2026-08-01,East,10\n2026-08-02,East,20\n2026-08-03,West,5\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_page_filter_is_scoped_persisted_and_recomputed_on_open(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        source_id = controller.activeTableId
        table_id = next(
            table["id"] for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

        self.assertTrue(controller.addPageFilter(table_id, "Region", "East"))
        self.assertEqual(controller.reportKpis["Revenue"], "30")
        self.assertEqual(len(controller.activePageFilters), 1)

        controller.add_page()
        second_page_index = controller.activePageIndex
        self.assertEqual(controller.reportKpis["Revenue"], "35")
        self.assertEqual(controller.activePageFilters, [])
        controller.setActivePage(0)
        self.assertEqual(controller.reportKpis["Revenue"], "30")

        project_path = self.root / "page-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Date,Region,Revenue\n"
            "2026-08-04,East,12\n2026-08-05,West,18\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Revenue"], "12")
        self.assertEqual(len(reopened.activePageFilters), 1)
        reopened.setActivePage(second_page_index)
        self.assertEqual(reopened.reportKpis["Revenue"], "30")
        self.assertEqual(reopened.activePageFilters, [])

        reopened.setActivePage(0)
        self.assertTrue(reopened.removePageFilter(0))
        self.assertEqual(reopened.reportKpis["Revenue"], "30")


if __name__ == "__main__":
    unittest.main()
