"""Acceptance checks for relative-date boundaries and saved filter scopes."""

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
    current = DateTime(2026, 10, 8, 12, 34, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


class RelativeDateFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        FrozenDateTime.current = DateTime(2026, 10, 8, 12, 34, tzinfo=timezone.utc)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Dated Sales.csv"
        self.source_path.write_text(
            "Date,Revenue\n"
            "2025-12-31,1\n2026-01-01,2\n2026-09-27,3\n"
            "2026-09-30,4\n2026-10-03,5\n2026-10-04,6\n"
            "2026-10-06,7\n2026-10-07,8\n2026-10-08,9\n"
            "2026-10-09,10\n2026-10-10,11\n2026-10-11,12\n"
            "2026-10-17,13\n2026-10-18,14\n2026-10-31,15\n"
            "2026-11-01,16\n2026-12-31,17\n2027-01-01,18\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        controller = StudioController(self.app, settings)
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(controller.setColumnType("Date", "date"))
        return controller

    @staticmethod
    def table_id(controller: StudioController) -> str:
        source_id = controller.activeTableId
        return next(
            table["id"] for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    def test_rolling_and_calendar_period_boundaries(self) -> None:
        controller = self.controller("boundary-settings.ini")
        table_id = self.table_id(controller)
        self.assertIn(
            "relative_date",
            {item["value"] for item in controller.pageFilterOperators("date")},
        )

        cases = [
            ("last", 2, "days", True, 17),
            ("last", 2, "days", False, 15),
            ("this", 99, "days", False, 9),
            ("next", 2, "days", True, 19),
            ("next", 2, "days", False, 21),
            ("last", 1, "weeks", True, 35),
            ("last", 1, "weeks", False, 26),
            ("next", 1, "weeks", True, 42),
            ("next", 1, "weeks", False, 33),
            ("last", 1, "calendar_weeks", True, 12),
            ("this", 1, "calendar_weeks", True, 51),
            ("next", 1, "calendar_weeks", True, 25),
            ("last", 1, "calendar_months", True, 7),
            ("this", 1, "calendar_months", True, 110),
            ("next", 1, "calendar_months", True, 16),
            ("last", 1, "calendar_years", True, 1),
            ("this", 1, "calendar_years", True, 152),
            ("next", 1, "calendar_years", True, 18),
        ]
        with patch("analytics_studio.controller.datetime", FrozenDateTime):
            for direction, count, unit, include_today, expected in cases:
                with self.subTest(direction=direction, unit=unit, include_today=include_today):
                    self.assertTrue(controller.addPageRelativeDateFilter(
                        table_id, "Date", direction, count, unit, include_today
                    ))
                    self.assertEqual(controller.reportKpis["Revenue"], str(expected))

    def test_page_visual_scopes_save_reopen_and_advance_at_utc_midnight(self) -> None:
        controller = self.controller("scope-settings.ini")
        table_id = self.table_id(controller)
        with patch("analytics_studio.controller.datetime", FrozenDateTime):
            self.assertTrue(controller.addPageRelativeDateFilter(
                table_id, "Date", "last", 2, "days", True
            ))
            self.assertEqual(controller.reportKpis["Revenue"], "17")
            visual_name = "Revenue KPI"
            controller.selectVisual(visual_name)
            self.assertTrue(controller.addVisualRelativeDateFilter(
                visual_name, table_id, "Date", "this", 7, "days", False
            ))
            self.assertEqual(controller.visualKpis[visual_name], "9")
            self.assertEqual(controller.reportKpis["Revenue"], "17")

            project_path = self.root / "relative-date-filters.npa"
            self.assertTrue(controller._save_to(project_path))
            self.source_path.write_text(
                "Date,Revenue\n2026-10-07,8\n2026-10-08,18\n2026-10-09,10\n",
                encoding="utf-8",
            )
            reopened = StudioController(
                self.app,
                QSettings(str(self.root / "scope-reopened.ini"), QSettings.Format.IniFormat),
            )
            self.assertTrue(reopened.open_project_path(project_path))
            self.assertEqual(reopened.reportKpis["Revenue"], "26")
            reopened.selectVisual(visual_name)
            self.assertEqual(reopened.visualKpis[visual_name], "18")
            self.assertEqual(len(reopened.activePageFilters), 1)
            self.assertEqual(len(reopened.activeVisualFilters), 1)

            FrozenDateTime.current = DateTime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
            reopened._on_relative_filter_boundary()
            self.assertEqual(reopened.reportKpis["Revenue"], "28")
            self.assertEqual(reopened.visualKpis[visual_name], "10")


if __name__ == "__main__":
    unittest.main()
