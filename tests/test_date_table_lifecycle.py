"""Acceptance checks for marking, saving, reopening, and refreshing a date table."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.date_table_dialog import DateTableDialog
from analytics_studio.file_import import parse_file


class DateTableLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Calendar.csv"
        self.source_path.write_text(
            "Date,Label\n2024-01-01,First\n2024-01-02,Second\n2024-01-03,Third\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def mark_date_table(self, controller: StudioController) -> bool:
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        tables = [
            dict(table) for table in controller.tableCatalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): controller._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = DateTableDialog(tables, candidates)
        dialog.column_combo.setCurrentText("Date")

        def accept_dialog() -> QDialog.DialogCode:
            dialog._accept_mark()
            return dialog.result()

        with (
            patch("analytics_studio.controller.DateTableDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
        ):
            result = controller.mark_date_table_dialog()
        dialog.deleteLater()
        return result

    def clear_date_table_mark(self, controller: StudioController) -> bool:
        tables = [
            dict(table) for table in controller.tableCatalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): controller._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = DateTableDialog(tables, candidates)

        def accept_dialog() -> QDialog.DialogCode:
            dialog._clear_mark()
            return dialog.result()

        with (
            patch("analytics_studio.controller.DateTableDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
        ):
            result = controller.mark_date_table_dialog()
        dialog.deleteLater()
        return result

    def test_marked_date_column_survives_project_reopen_and_valid_refresh(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(self.mark_date_table(controller), controller.statusMessage)

        table = next(item for item in controller._project["model"]["tables"])
        self.assertEqual(table["date_column"], "Date")
        self.assertEqual(controller.tableCatalog[0]["dateColumn"], "Date")
        source_id = str(table["source_id"])
        project_path = self.root / "marked-date-table.npa"
        self.assertTrue(controller._save_to(project_path))

        self.source_path.write_text(
            "Date,Label\n2024-01-02,Updated\n2024-01-03,Third\n2024-01-04,Fourth\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._project["model"]["tables"][0]["date_column"], "Date"
        )
        self.assertEqual(
            [row["Date"] for row in reopened._loaded_candidates[source_id].rows],
            ["2024-01-02", "2024-01-03", "2024-01-04"],
        )
        self.source_path.write_text(
            "Date,Label\n2024-01-03,Third\n2024-01-04,Fourth\n2024-01-05,Fifth\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(
            [row["Date"] for row in reopened._loaded_candidates[source_id].rows],
            ["2024-01-03", "2024-01-04", "2024-01-05"],
        )
        self.assertEqual(
            reopened._project["model"]["tables"][0]["date_column"], "Date"
        )

    def test_refresh_rejects_a_calendar_with_a_missing_date_and_keeps_old_rows(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(self.mark_date_table(controller), controller.statusMessage)
        source_id = controller._active_source_id
        original_rows = list(controller._loaded_candidates[source_id].rows)

        self.source_path.write_text(
            "Date,Label\n2024-01-01,First\n2024-01-03,Third\n2024-01-04,Fourth\n",
            encoding="utf-8",
        )
        with patch("analytics_studio.controller.QMessageBox.critical"):
            controller.refresh_all_sources()

        self.assertEqual(controller._loaded_candidates[source_id].rows, original_rows)
        self.assertEqual(
            controller._model_table_for_source(controller._project, source_id)["date_column"],
            "Date",
        )
        self.assertIn("missing date", controller.sourceWarning.casefold())

    def test_marked_date_table_survives_same_source_reimport(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(self.mark_date_table(controller), controller.statusMessage)
        source_id = controller._active_source_id

        self.source_path.write_text(
            "Date,Label\n2024-02-01,One\n2024-02-02,Two\n2024-02-03,Three\n",
            encoding="utf-8",
        )
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ), controller.statusMessage)

        self.assertEqual(controller._active_source_id, source_id)
        self.assertEqual(controller._rows[0]["Date"], "2024-02-01")
        table = controller._model_table_for_source(controller._project, source_id)
        self.assertEqual(table["date_column"], "Date")
        self.assertEqual(table["column_types"]["Date"], "date")

    def test_marked_date_column_can_switch_between_date_and_datetime(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(self.mark_date_table(controller), controller.statusMessage)

        self.assertTrue(controller.setColumnType("Date", "datetime"), controller.statusMessage)
        self.assertEqual(controller._project["model"]["tables"][0]["date_column"], "Date")
        self.assertEqual(controller._project["model"]["tables"][0]["column_types"]["Date"], "datetime")
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.assertEqual(controller._project["model"]["tables"][0]["date_column"], "Date")
        self.assertEqual(controller._project["model"]["tables"][0]["column_types"]["Date"], "date")
        self.assertEqual(controller._rows[0]["Date"], "2024-01-01")

    def test_user_can_clear_an_existing_date_table_mark(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        self.assertTrue(self.mark_date_table(controller), controller.statusMessage)
        self.assertTrue(
            self.clear_date_table_mark(controller), controller.statusMessage
        )

        table = controller._project["model"]["tables"][0]
        self.assertIsNone(table["date_column"])
        self.assertFalse(controller.tableCatalog[0]["dateColumn"])

    def test_modeling_command_routes_to_date_table_dialog(self) -> None:
        controller = self.controller("settings.ini")

        with patch.object(controller, "mark_date_table_dialog") as mark_dialog:
            controller.executeCommand("markDateTable")

        mark_dialog.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
