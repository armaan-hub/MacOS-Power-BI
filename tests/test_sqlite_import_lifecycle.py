"""Acceptance checks for SQLite table and view imports."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.import_preview_dialog import FileImportPreviewDialog


class SQLiteImportLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "metrics.sqlite"
        with closing(sqlite3.connect(self.database_path)) as database:
            with database:
                database.execute(
                    "CREATE TABLE metrics (id INTEGER, amount INTEGER, note TEXT)"
                )
                database.executemany(
                    "INSERT INTO metrics VALUES (?, ?, ?)",
                    [(1, 10, None), (2, 20, "initial")],
                )
                database.execute(
                    "CREATE VIEW metrics_view AS "
                    "SELECT id, amount, amount * 2 AS doubled FROM metrics"
                )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 5
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def import_sqlite_object(
        self,
        controller: StudioController,
        table_name: str,
        existing: set[str] | None = None,
    ) -> str:
        dialog = FileImportPreviewDialog(
            self.database_path,
            replacing=False,
            existing_sqlite_tables=existing,
        )
        self.wait_for_preview(dialog)
        self.assertIsNotNone(dialog.table_combo.findData(table_name))
        dialog.table_combo.setCurrentIndex(dialog.table_combo.findData(table_name))
        self.wait_for_preview(dialog)
        candidate = dialog._preview_candidate
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.options["table_name"], table_name)
        dialog._accept_candidate()
        self.assertIsNotNone(dialog.candidate)
        self.assertTrue(controller._commit_import(self.database_path, dialog.candidate))
        source_id = controller.activeTableId
        dialog.deleteLater()
        return source_id

    def test_table_and_view_import_save_reopen_and_refresh_independently(self) -> None:
        controller = self.controller("settings.ini")
        table_id = self.import_sqlite_object(controller, "metrics")
        view_id = self.import_sqlite_object(controller, "metrics_view", {"metrics"})

        self.assertNotEqual(table_id, view_id)
        self.assertEqual(
            controller._loaded_candidates[table_id].rows,
            [
                {"id": "1", "amount": "10", "note": ""},
                {"id": "2", "amount": "20", "note": "initial"},
            ],
        )
        self.assertEqual(
            controller._loaded_candidates[view_id].rows,
            [
                {"id": "1", "amount": "10", "doubled": "20"},
                {"id": "2", "amount": "20", "doubled": "40"},
            ],
        )

        project_path = self.root / "sqlite-project.npa"
        self.assertTrue(controller._save_to(project_path))
        with closing(sqlite3.connect(self.database_path)) as database:
            with database:
                database.execute("UPDATE metrics SET amount = 15 WHERE id = 1")
                database.execute("INSERT INTO metrics VALUES (3, 30, 'new')")

        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._loaded_candidates[table_id].rows[-1],
            {"id": "3", "amount": "30", "note": "new"},
        )
        self.assertEqual(
            reopened._loaded_candidates[view_id].rows[-1],
            {"id": "3", "amount": "30", "doubled": "60"},
        )

        with closing(sqlite3.connect(self.database_path)) as database:
            with database:
                database.execute("UPDATE metrics SET amount = 25 WHERE id = 1")
        reopened.refresh_all_sources()
        self.assertEqual(
            reopened._loaded_candidates[table_id].rows[0]["amount"], "25"
        )
        self.assertEqual(
            reopened._loaded_candidates[view_id].rows[0]["doubled"], "50"
        )

    def test_recent_source_reopens_the_last_selected_sqlite_object(self) -> None:
        controller = self.controller("settings.ini")
        self.import_sqlite_object(controller, "metrics_view")

        recent = controller._recent_source_store.sources
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].kind, "sqlite")
        self.assertEqual(recent[0].parser_options, {"table_name": "metrics_view"})

        selected: list[str] = []

        def accept_preview(dialog: FileImportPreviewDialog) -> QDialog.DialogCode:
            self.wait_for_preview(dialog)
            selected.append(dialog.table_combo.currentData())
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(FileImportPreviewDialog, "exec", new=accept_preview):
            self.assertTrue(controller.openRecentSource(0))

        self.assertEqual(selected, ["metrics_view"])
        self.assertEqual(
            controller._loaded_candidates[controller.activeTableId].rows[0],
            {"id": "1", "amount": "10", "doubled": "20"},
        )


if __name__ == "__main__":
    unittest.main()
