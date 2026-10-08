"""Acceptance checks for folder-combine and local Parquet workflows."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyarrow as pa
import pyarrow.parquet as parquet
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCancelledError, parse_file
from analytics_studio.folder_import import default_folder_options, parse_folder
from analytics_studio.folder_import_dialog import FolderImportDialog
from analytics_studio.import_preview_dialog import FileImportPreviewDialog


class LocalSourceExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str = "settings.ini") -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def _wait_until(self, predicate, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        self.app.processEvents()
        return predicate()

    def test_folder_dialog_import_save_reopen_and_refresh(self) -> None:
        folder = self.root / "monthly"
        north = folder / "north"
        south = folder / "south"
        north.mkdir(parents=True)
        south.mkdir()
        (north / "records.csv").write_text(
            "id,amount\nN,10\n", encoding="utf-8"
        )
        south_records = south / "records.csv"
        south_records.write_text("id,amount\nS,20\n", encoding="utf-8")
        (folder / "ignore.csv").write_text("id,amount\nX,99\n", encoding="utf-8")

        options = default_folder_options()
        options.update(
            recursive=True,
            name_contains="records",
            sample_file="north/records.csv",
            include_source_name=True,
        )
        dialog = FolderImportDialog(
            folder, replacing=False, initial_options=options
        )
        self.assertTrue(self._wait_until(lambda: len(dialog._files) == 2))
        self.assertEqual(len(dialog._files), 2)
        dialog._preview_combined()
        self.assertTrue(self._wait_until(lambda: dialog.import_button.isEnabled()))
        preview = dialog.table.model()
        self.assertEqual(preview.rowCount(), 2)
        self.assertEqual(preview.columnCount(), 3)
        dialog._accept_candidate()
        candidate = dialog.candidate
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.headers, ["Source.Name", "id", "amount"])
        self.assertEqual(candidate.rows[0], {
            "Source.Name": "north/records.csv", "id": "N", "amount": "10",
        })

        controller = self.controller()
        self.assertTrue(controller._commit_import(folder, candidate))
        source_id = controller.activeTableId
        project_path = self.root / "folder-project.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, source_id)
        self.assertEqual(reopened._active_source_kind, "folder")
        south_records.write_text("id,amount\nS,200\n", encoding="utf-8")
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[source_id].rows, [
            {"Source.Name": "north/records.csv", "id": "N", "amount": "10"},
            {"Source.Name": "south/records.csv", "id": "S", "amount": "200"},
        ])
        dialog.deleteLater()

    def test_folder_parser_reports_progress_and_cancels_cooperatively(self) -> None:
        folder = self.root / "monthly"
        folder.mkdir()
        (folder / "records.csv").write_text(
            "id,amount\nA,10\n", encoding="utf-8"
        )
        (folder / "more.csv").write_text(
            "id,amount\nB,20\n", encoding="utf-8"
        )
        options = default_folder_options()
        options["sample_file"] = "records.csv"
        messages: list[str] = []
        candidate = parse_folder(folder, options, progress_callback=messages.append)
        self.assertEqual(candidate.row_count, 2)
        self.assertTrue(any(message.startswith("Reading file ") and "of 2" in message for message in messages))
        self.assertEqual(messages[-1], "Combined 2 files.")

        messages.clear()
        cancel_event = threading.Event()

        def cancel_after_sample_starts(message: str) -> None:
            messages.append(message)
            if message.startswith("Reading sample file"):
                cancel_event.set()

        with self.assertRaises(ImportCancelledError):
            parse_folder(
                folder,
                options,
                cancel_event=cancel_event,
                progress_callback=cancel_after_sample_starts,
            )
        self.assertTrue(any(message.startswith("Reading sample file") for message in messages))

    def test_folder_preview_can_be_canceled_while_worker_is_running(self) -> None:
        folder = self.root / "monthly"
        folder.mkdir()
        (folder / "records.csv").write_text(
            "id,amount\nA,10\n", encoding="utf-8"
        )
        started = threading.Event()

        def wait_for_cancel(
            _folder,
            _options,
            *,
            cancel_event: threading.Event,
            progress_callback,
        ):
            started.set()
            progress_callback("Reading file 1 of 1: records.csv…")
            cancel_event.wait(2)
            raise ImportCancelledError("Import canceled.")

        with patch("analytics_studio.folder_import_dialog.parse_folder", side_effect=wait_for_cancel):
            dialog = FolderImportDialog(folder, replacing=False)
            self.assertTrue(self._wait_until(lambda: bool(dialog._files)))
            dialog._preview_combined()
            self.assertTrue(started.wait(1))
            self.assertEqual(dialog.preview_button.text(), "Cancel preview")
            dialog._toggle_preview()
            self.assertFalse(dialog.import_button.isEnabled())
            self.assertTrue(self._wait_until(lambda: not dialog._parse_tasks))
            self.assertEqual(dialog.count_label.text(), "Combined preview canceled.")
            dialog.reject()

    def test_folder_file_discovery_runs_in_background_and_can_be_canceled(self) -> None:
        folder = self.root / "monthly"
        folder.mkdir()
        (folder / "records.csv").write_text(
            "id,amount\nA,10\n", encoding="utf-8"
        )
        started = threading.Event()
        observed_args: list[tuple[str, bool, str]] = []

        def wait_for_cancel(
            _folder,
            *,
            file_kind: str,
            recursive: bool,
            name_contains: str,
            cancel_event: threading.Event,
            progress_callback,
        ):
            observed_args.append((file_kind, recursive, name_contains))
            started.set()
            progress_callback("Scanning folder… 500 entries checked")
            cancel_event.wait(2)
            raise ImportCancelledError("Import canceled.")

        with patch(
            "analytics_studio.folder_import_dialog.discover_folder_files",
            side_effect=wait_for_cancel,
        ):
            dialog = FolderImportDialog(folder, replacing=False)
            self.assertTrue(started.wait(1))
            self.assertEqual(observed_args, [("csv", False, "")])
            self.assertEqual(dialog.preview_button.text(), "Cancel scan")
            dialog._toggle_preview()
            self.assertTrue(self._wait_until(lambda: not dialog._discovery_tasks))
            self.assertEqual(dialog.preview_button.text(), "Scan folder")
            self.assertEqual(dialog.files_label.text(), "Folder scan canceled.")
            dialog.reject()

    def test_parquet_preview_import_save_reopen_and_refresh(self) -> None:
        source_path = self.root / "metrics.parquet"
        parquet.write_table(
            pa.Table.from_pylist([{"id": "A", "value": 10}]), source_path
        )

        dialog = FileImportPreviewDialog(source_path, replacing=False)
        self.assertTrue(dialog.import_button.isEnabled())
        preview = dialog.table.model()
        self.assertEqual(preview.rowCount(), 1)
        self.assertEqual(preview.columnCount(), 2)
        self.assertEqual(preview.data(preview.index(0, 1)), "10")
        dialog._accept_candidate()
        candidate = dialog.candidate
        self.assertIsNotNone(candidate)
        assert candidate is not None

        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, candidate))
        source_id = controller.activeTableId
        project_path = self.root / "parquet-project.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, source_id)
        self.assertEqual(reopened._active_source_kind, "parquet")
        parquet.write_table(
            pa.Table.from_pylist([
                {"id": "A", "value": 11},
                {"id": "B", "value": 12},
            ]),
            source_path,
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[source_id].rows, [
            {"id": "A", "value": "11"},
            {"id": "B", "value": "12"},
        ])
        self.assertEqual(parse_file(source_path).kind, "parquet")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
