"""Acceptance checks for calendar table creation and dynamic refresh."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.calendar_table_dialog import CalendarTableDialog
from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file


class CalendarTableLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sales_path = self.root / "Sales.csv"
        self.sales_path.write_text(
            "SalesDate,Amount\n2020-03-15,10\n2022-08-05,20\n",
            encoding="utf-8",
        )
        self.forecast_path = self.root / "Forecast.csv"
        self.forecast_path.write_text(
            "Expected,Label\n2021-02-20T23:30:00,First\n2022-07-01T08:00:00,Last\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(str(self.root / settings_name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def create_calendar_table(
        self,
        controller: StudioController,
        *,
        mode: str,
        name: str,
        start: QDate | None = None,
        end: QDate | None = None,
        fiscal_month: int = 12,
    ) -> bool:
        tables = [
            dict(table) for table in controller._table_catalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): controller._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = CalendarTableDialog(tables, candidates)
        dialog.table_name_edit.setText(name)
        if mode == "calendar_auto":
            dialog.range_mode_combo.setCurrentIndex(1)
            dialog.fiscal_month_combo.setCurrentIndex(fiscal_month - 1)
        if start is not None:
            dialog.start_date_edit.setDate(start)
        if end is not None:
            dialog.end_date_edit.setDate(end)

        def accept_dialog() -> QDialog.DialogCode:
            dialog._accept_table()
            return dialog.result()

        with (
            patch("analytics_studio.controller.CalendarTableDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
        ):
            result = controller.calendar_table_dialog()
        dialog.deleteLater()
        return result

    def test_manual_calendar_table_is_marked_and_reopens(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(self.create_calendar_table(
            controller,
            mode="calendar",
            name="Leap calendar",
            start=QDate(2024, 2, 28),
            end=QDate(2024, 3, 1),
        ), controller.statusMessage)

        source = controller._project["data_sources"][0]
        source_id = source["id"]
        self.assertEqual(source["query_definition"], {
            "operation": "calendar",
            "source_ids": [],
            "start_date": "2024-02-28",
            "end_date": "2024-03-01",
        })
        table = controller._model_table_for_source(controller._project, source_id)
        self.assertEqual(table["date_column"], "Date")
        self.assertEqual(table["column_types"]["Date"], "date")
        self.assertEqual(controller._loaded_candidates[source_id].rows, [
            {"Date": "2024-02-28"},
            {"Date": "2024-02-29"},
            {"Date": "2024-03-01"},
        ])
        self.assertEqual(controller.tableCatalog[0]["queryExpression"],
                         "CALENDAR(DATE(2024, 2, 28), DATE(2024, 3, 1))")

        project_path = self.root / "manual-calendar.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._loaded_candidates[source_id].rows,
                         controller._loaded_candidates[source_id].rows)
        self.assertEqual(
            reopened._model_table_for_source(reopened._project, source_id)["date_column"],
            "Date",
        )

    def test_auto_calendar_tracks_fiscal_year_bounds_and_new_sources(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.sales_path, parse_file(self.sales_path)
        ))
        sales_id = controller._active_source_id
        self.assertTrue(controller.setColumnType("SalesDate", "date"), controller.statusMessage)
        self.assertTrue(controller._commit_import(
            self.forecast_path, parse_file(self.forecast_path)
        ))
        forecast_id = controller._active_source_id
        self.assertTrue(controller.setColumnType("Expected", "datetime"), controller.statusMessage)

        self.assertTrue(self.create_calendar_table(
            controller,
            mode="calendar_auto",
            name="Fiscal calendar",
            fiscal_month=3,
        ), controller.statusMessage)
        calendar_source = next(
            source for source in controller._project["data_sources"]
            if source.get("query_definition", {}).get("operation") == "calendar_auto"
        )
        calendar_id = str(calendar_source["id"])
        self.assertEqual(calendar_source["query_definition"]["source_ids"], [
            str(sales_id), str(forecast_id),
        ])
        calendar_rows = controller._loaded_candidates[calendar_id].rows
        self.assertEqual(calendar_rows[0]["Date"], "2019-04-01")
        self.assertEqual(calendar_rows[-1]["Date"], "2023-03-31")
        table = controller._model_table_for_source(controller._project, calendar_id)
        self.assertEqual(table["date_column"], "Date")
        self.assertEqual(controller.tableCatalog[-1]["queryExpression"], "CALENDARAUTO(3)")

        late_source_path = self.root / "Late.csv"
        late_source_path.write_text(
            "ExtraDate\n2018-11-10\n", encoding="utf-8"
        )
        self.assertTrue(controller._commit_import(
            late_source_path, parse_file(late_source_path)
        ))
        late_id = str(controller._active_source_id)
        self.assertTrue(controller.setColumnType("ExtraDate", "date"), controller.statusMessage)
        self.assertEqual(
            controller._loaded_candidates[calendar_id].rows[0]["Date"],
            "2018-04-01",
        )
        self.assertIn(
            late_id,
            next(source for source in controller._project["data_sources"]
                 if source["id"] == calendar_id)["query_definition"]["source_ids"],
        )

        project_path = self.root / "auto-calendar.npa"
        self.assertTrue(controller._save_to(project_path))
        late_source_path.write_text(
            "ExtraDate\n2024-05-10\n", encoding="utf-8"
        )
        reopened = self.controller("auto-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._loaded_candidates[calendar_id].rows[-1]["Date"],
            "2025-03-31",
        )

        late_source_path.write_text(
            "ExtraDate\n2026-05-10\n", encoding="utf-8"
        )
        reopened.refresh_all_sources()
        self.assertEqual(
            reopened._loaded_candidates[calendar_id].rows[-1]["Date"],
            "2027-03-31",
        )


if __name__ == "__main__":
    unittest.main()
