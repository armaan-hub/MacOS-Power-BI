"""Acceptance checks for relative-time UTC boundaries and filter lifecycle."""

from __future__ import annotations

from datetime import datetime as DateTime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


class FrozenDateTime(DateTime):
    current = DateTime(2026, 10, 8, 12, 34, 45, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


class RelativeTimeFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        FrozenDateTime.current = DateTime(2026, 10, 8, 12, 34, 45, tzinfo=timezone.utc)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Timed Sales.csv"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str, rows: str) -> StudioController:
        self.source_path.write_text("Timestamp,Revenue\n" + rows, encoding="utf-8")
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        controller = StudioController(self.app, settings)
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(controller.setColumnType("Timestamp", "datetime"))
        return controller

    @staticmethod
    def table_id(controller: StudioController) -> str:
        source_id = controller.activeTableId
        return next(
            table["id"] for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    def test_minute_hour_offsets_and_inclusive_rolling_boundaries(self) -> None:
        rows = (
            "2026-10-08T10:34:44Z,1\n"
            "2026-10-08T10:34:45Z,2\n"
            "2026-10-08T11:59:59Z,3\n"
            "2026-10-08T12:00:00Z,4\n"
            "2026-10-08T12:34:00Z,5\n"
            "2026-10-08T12:34:44Z,6\n"
            "2026-10-08T12:34:45Z,7\n"
            "2026-10-08T12:34:59Z,8\n"
            "2026-10-08T12:35:00Z,9\n"
            "2026-10-08T12:36:45Z,10\n"
            "2026-10-08T12:36:46Z,11\n"
            "2026-10-08T12:59:59Z,12\n"
            "2026-10-08T13:00:00Z,13\n"
            "2026-10-08T16:34:30+04:00,14\n"
            "2026-10-08T12:34:20,15\n"
            "2026-10-08T12:32:45Z,16\n"
            "2026-10-08T12:32:44Z,17\n"
        )
        controller = self.controller("boundary-settings.ini", rows)
        table_id = self.table_id(controller)
        self.assertIn(
            "relative_time",
            {item["value"] for item in controller.pageFilterOperators("datetime")},
        )
        cases = [
            ("last", 2, "minutes", 63),
            ("this", 99, "minutes", 55),
            ("next", 2, "minutes", 34),
            ("last", 2, "hours", 89),
            ("this", 99, "hours", 134),
            ("next", 2, "hours", 70),
        ]
        with patch("analytics_studio.controller.datetime", FrozenDateTime):
            for direction, count, unit, expected in cases:
                with self.subTest(direction=direction, unit=unit):
                    self.assertTrue(controller.addPageRelativeTimeFilter(
                        table_id, "Timestamp", direction, count, unit
                    ))
                    self.assertEqual(controller.reportKpis["Revenue"], str(expected))

    def test_page_visual_scopes_reopen_and_recalculate_at_minute_boundary(self) -> None:
        initial_rows = (
            "2026-10-08T12:32:45Z,2\n"
            "2026-10-08T12:34:00Z,3\n"
            "2026-10-08T12:34:44Z,4\n"
            "2026-10-08T12:34:45Z,5\n"
            "2026-10-08T12:34:59Z,6\n"
            "2026-10-08T12:35:00Z,7\n"
            "2026-10-08T16:34:30+04:00,8\n"
            "2026-10-08T12:34:20,9\n"
        )
        controller = self.controller("scope-settings.ini", initial_rows)
        table_id = self.table_id(controller)
        with patch("analytics_studio.controller.datetime", FrozenDateTime):
            self.assertTrue(controller.addPageRelativeTimeFilter(
                table_id, "Timestamp", "last", 2, "minutes"
            ))
            self.assertEqual(controller.reportKpis["Revenue"], "31")
            visual_name = "Revenue KPI"
            controller.selectVisual(visual_name)
            self.assertTrue(controller.addVisualRelativeTimeFilter(
                visual_name, table_id, "Timestamp", "this", 8, "minutes"
            ))
            self.assertEqual(controller.visualKpis[visual_name], "29")
            self.assertEqual(controller.reportKpis["Revenue"], "31")

            project_path = self.root / "relative-time-filters.npa"
            self.assertTrue(controller._save_to(project_path))
            self.source_path.write_text(
                "Timestamp,Revenue\n"
                "2026-10-08T12:32:45Z,20\n"
                "2026-10-08T12:34:00Z,30\n"
                "2026-10-08T12:34:59Z,50\n"
                "2026-10-08T12:35:00Z,60\n"
                "2026-10-08T16:34:30+04:00,70\n"
                "2026-10-08T12:34:20,80\n",
                encoding="utf-8",
            )
            reopened = StudioController(
                self.app,
                QSettings(str(self.root / "scope-reopened.ini"), QSettings.Format.IniFormat),
            )
            self.assertTrue(reopened.open_project_path(project_path))
            self.assertEqual(reopened.reportKpis["Revenue"], "200")
            reopened.selectVisual(visual_name)
            self.assertEqual(reopened.visualKpis[visual_name], "180")
            self.assertEqual(len(reopened.activePageFilters), 1)
            self.assertEqual(len(reopened.activeVisualFilters), 1)

            FrozenDateTime.current = DateTime(2026, 10, 8, 12, 35, 0, tzinfo=timezone.utc)
            reopened._on_relative_filter_boundary()
            self.assertEqual(reopened.reportKpis["Revenue"], "290")
            self.assertEqual(reopened.visualKpis[visual_name], "60")


if __name__ == "__main__":
    unittest.main()
