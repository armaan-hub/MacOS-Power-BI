"""Preview, commit, save, reopen, and refresh behavior for file imports."""

from __future__ import annotations

import copy
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Any
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCancelledError, parse_file
from analytics_studio.import_preview_dialog import FileImportPreviewDialog


class ImportLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])
        families = QFontDatabase.families()
        if families:
            cls.app.setFont(QFont(families[0]))

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )

    def new_controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 5
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_xlsx(self, path: Path) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        sheet = '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="inlineStr"><is><t>name</t></is></c><c r="B1" t="inlineStr"><is><t>amount</t></is></c></row>
 <row r="2"><c r="A2" t="inlineStr"><is><t>Ada</t></is></c><c r="B2"><v>12</v></c></row>
</sheetData></worksheet>'''
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    def test_preview_requires_accept_and_uses_selected_csv_options(self) -> None:
        path = self.root / "sales.csv"
        path.write_text("name;amount\nAda;12\n", encoding="utf-8")

        dialog = FileImportPreviewDialog(path, replacing=False)

        self.assertIsNone(dialog.candidate)
        self.assertEqual(dialog.table.model().columnCount(), 1)
        dialog.delimiter_combo.setCurrentIndex(dialog.delimiter_combo.findData(";"))
        preview = dialog.table.model()
        self.assertEqual(preview.columnCount(), 2)
        self.assertEqual(preview.rowCount(), 1)
        self.assertEqual(preview.data(preview.index(0, 0)), "Ada")

        dialog._accept_candidate()

        self.assertEqual(dialog.candidate.options["delimiter"], ";")
        self.assertEqual(dialog.candidate.rows, [{"name": "Ada", "amount": "12"}])

    def test_preview_restores_parser_options_for_a_recent_source(self) -> None:
        path = self.root / "sales.csv"
        path.write_text("name;amount\nAda;12\n", encoding="utf-8")

        dialog = FileImportPreviewDialog(
            path, replacing=False, initial_options={"delimiter": ";"}
        )

        self.assertEqual(dialog.table.model().columnCount(), 2)
        self.assertEqual(dialog.table.model().data(dialog.table.model().index(0, 0)), "Ada")

    def test_large_preview_runs_in_background_and_reports_completion(self) -> None:
        path = self.root / "large-preview.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write("id,description\n")
            for row_index in range(6_000):
                stream.write(f"{row_index},{'x' * 60}\n")

        dialog = FileImportPreviewDialog(path, replacing=False)
        self.assertIsNotNone(dialog._active_parse_id)
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertFalse(dialog.progress_widget.isHidden())

        deadline = time.monotonic() + 5
        while dialog._active_parse_id is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()

        self.assertIsNone(dialog._active_parse_id)
        self.assertTrue(dialog.import_button.isEnabled())
        self.assertTrue(dialog.progress_widget.isHidden())
        self.assertEqual(dialog.table.model().rowCount(), 100)
        self.assertIn("6,000 rows total", dialog.count_label.text())
        dialog._accept_candidate()
        self.assertEqual(dialog.candidate.row_count, 6_000)

    def test_cancel_dialog_stops_a_background_preview(self) -> None:
        path = self.root / "large-cancel.csv"
        path.write_bytes(b"x" * (256 * 1024 + 1))
        parser_started = threading.Event()
        cancellation_seen = threading.Event()

        def wait_for_cancel(
            _path: Path,
            *,
            options: dict[str, object],
            cancel_event: threading.Event,
            progress_callback: object,
        ) -> None:
            del options
            assert callable(progress_callback)
            progress_callback("Read 5,000 CSV rows…")
            parser_started.set()
            cancel_event.wait(2)
            if cancel_event.is_set():
                cancellation_seen.set()
            raise ImportCancelledError("Import canceled.")

        with patch(
            "analytics_studio.import_preview_dialog.parse_file",
            side_effect=wait_for_cancel,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.assertTrue(parser_started.wait(2))
            self.app.processEvents()
            self.assertIn("5,000 CSV rows", dialog.progress_label.text())
            dialog.reject()
            self.assertTrue(cancellation_seen.wait(2))

        self.assertIsNone(dialog._accepted_candidate)

    def test_excel_options_are_discovered_off_ui_thread_before_preview(self) -> None:
        path = self.root / "async-options.xlsx"
        self.write_xlsx(path)
        discovery_started = threading.Event()
        release_discovery = threading.Event()
        discovery_finished = threading.Event()
        worker_thread_ids: list[int] = []
        parser_thread_ids: list[int] = []

        def blocked_discovery(*_args: object, **_kwargs: object) -> tuple[list[str], str]:
            worker_thread_ids.append(threading.get_ident())
            discovery_started.set()
            release_discovery.wait(2)
            discovery_finished.set()
            return ["Data"], "Data"

        def record_parse(*args: Any, **kwargs: Any) -> object:
            parser_thread_ids.append(threading.get_ident())
            return parse_file(*args, **kwargs)

        with (
            patch(
                "analytics_studio.import_preview_dialog.inspect_excel_options",
                side_effect=blocked_discovery,
            ),
            patch(
                "analytics_studio.import_preview_dialog.parse_file",
                side_effect=record_parse,
            ) as parse_mock,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.assertTrue(discovery_started.wait(2))
            self.assertNotEqual(worker_thread_ids[0], threading.get_ident())
            self.assertFalse(dialog.import_button.isEnabled())
            self.assertFalse(dialog.progress_widget.isHidden())
            self.assertEqual(parse_mock.call_count, 0)

            timer_fired: list[bool] = []
            QTimer.singleShot(0, lambda: timer_fired.append(True))
            self.app.processEvents()
            self.assertEqual(timer_fired, [True])
            self.assertEqual(parse_mock.call_count, 0)

            release_discovery.set()
            self.wait_for_preview(dialog)

        self.assertTrue(discovery_finished.is_set())
        self.assertEqual(dialog.sheet_combo.currentText(), "Data")
        self.assertEqual(dialog.table.model().rowCount(), 1)
        self.assertEqual(parse_mock.call_count, 1)
        self.assertNotEqual(parser_thread_ids[0], threading.get_ident())
        dialog.deleteLater()

    def test_canceling_sqlite_options_discovery_ignores_late_results(self) -> None:
        path = self.root / "async-options.sqlite"
        with sqlite3.connect(path) as database:
            database.execute("CREATE TABLE metrics (id INTEGER)")

        discovery_started = threading.Event()
        release_discovery = threading.Event()
        discovery_finished = threading.Event()
        worker_thread_ids: list[int] = []

        def blocked_discovery(*_args: object, **_kwargs: object) -> list[str]:
            worker_thread_ids.append(threading.get_ident())
            discovery_started.set()
            release_discovery.wait(2)
            discovery_finished.set()
            return ["metrics"]

        with (
            patch(
                "analytics_studio.import_preview_dialog.list_sqlite_tables",
                side_effect=blocked_discovery,
            ),
            patch("analytics_studio.import_preview_dialog.parse_file", wraps=parse_file) as parse_mock,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.assertTrue(discovery_started.wait(2))
            self.assertNotEqual(worker_thread_ids[0], threading.get_ident())
            self.assertFalse(dialog.import_button.isEnabled())
            self.assertFalse(dialog.progress_widget.isHidden())
            timer_fired: list[bool] = []
            QTimer.singleShot(0, lambda: timer_fired.append(True))
            self.app.processEvents()
            self.assertEqual(timer_fired, [True])
            request_id = dialog._active_options_id
            self.assertIsNotNone(request_id)
            cancel_event = dialog._options_events[request_id]

            dialog.reject()
            self.assertTrue(cancel_event.is_set())
            release_discovery.set()
            self.assertTrue(discovery_finished.wait(2))
            deadline = time.monotonic() + 2
            while dialog._options_tasks and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.app.processEvents()

        self.assertEqual(parse_mock.call_count, 0)
        self.assertIsNone(dialog._preview_candidate)

    def test_sqlite_preview_parsing_runs_in_worker_after_options(self) -> None:
        path = self.root / "async-parse.sqlite"
        with closing(sqlite3.connect(path)) as database:
            with database:
                database.execute("CREATE TABLE metrics (id INTEGER, name TEXT)")
                database.execute("INSERT INTO metrics VALUES (1, 'Ada')")
        parser_thread_ids: list[int] = []

        def record_parse(*args: Any, **kwargs: Any) -> object:
            parser_thread_ids.append(threading.get_ident())
            return parse_file(*args, **kwargs)

        with patch(
            "analytics_studio.import_preview_dialog.parse_file",
            side_effect=record_parse,
        ):
            dialog = FileImportPreviewDialog(path, replacing=False)
            self.wait_for_preview(dialog)

        self.assertEqual(len(parser_thread_ids), 1)
        self.assertNotEqual(parser_thread_ids[0], threading.get_ident())
        self.assertEqual(dialog.table.model().rowCount(), 1)
        self.assertEqual(dialog.table.model().data(dialog.table.model().index(0, 1)), "Ada")
        dialog.deleteLater()

    def test_preview_commit_and_reopen_work_for_all_supported_file_formats(self) -> None:
        csv_path = self.root / "sales.csv"
        csv_path.write_text("name,amount\nAda,12\n", encoding="utf-8")
        excel_path = self.root / "sales.xlsx"
        self.write_xlsx(excel_path)
        json_path = self.root / "sales.json"
        json_path.write_text('[{"name":"Ada","amount":12}]', encoding="utf-8")
        xml_path = self.root / "sales.xml"
        xml_path.write_text(
            "<root><record><name>Ada</name><amount>12</amount></record></root>",
            encoding="utf-8",
        )

        expected = {"name": "Ada", "amount": "12"}
        for source_path in (csv_path, excel_path, json_path, xml_path):
            with self.subTest(kind=source_path.suffix):
                controller = self.new_controller()
                dialog = FileImportPreviewDialog(source_path, replacing=False)
                if source_path.suffix in {".xlsx", ".xlsm", ".xls"}:
                    self.wait_for_preview(dialog)
                self.assertIsNone(dialog.candidate)
                self.assertEqual(dialog.table.model().rowCount(), 1)
                self.assertEqual(dialog.table.model().columnCount(), 2)

                dialog._accept_candidate()
                candidate = dialog.candidate
                self.assertEqual(candidate.rows, [expected])
                self.assertTrue(controller._commit_import(source_path, candidate))
                self.assertEqual(controller._rows, [expected])

                project_path = self.root / f"{source_path.stem}.npa"
                self.assertTrue(controller._save_to(project_path))
                reopened = self.new_controller()
                self.assertTrue(reopened.open_project_path(project_path))
                self.assertEqual(reopened._rows, [expected])
                self.assertEqual(reopened._active_source_kind, candidate.kind)
                self.assertEqual(reopened._active_parser_options, candidate.options)

    def test_catalog_file_entries_route_to_the_matching_importer(self) -> None:
        controller = self.new_controller()
        cases = {
            "file_text_csv": "csv",
            "file_excel_workbook": "excel",
            "file_json": "json",
            "file_xml": "xml",
        }

        with patch.object(controller, "import_data_dialog") as import_dialog:
            for source_id, kind in cases.items():
                with self.subTest(source_id=source_id):
                    self.assertTrue(controller.connectDataSource(source_id))
                    import_dialog.assert_called_with(expected_kind=kind)

    def test_unavailable_service_connectors_do_not_open_importers(self) -> None:
        controller = self.new_controller()
        original_project = copy.deepcopy(controller._project)
        unavailable_sources = (
            "microsoft_onelake_catalog",
            "microsoft_dataverse",
            "power_bi_power_bi_semantic_models",
        )

        with patch.object(controller, "import_data_dialog") as import_dialog:
            for source_id in unavailable_sources:
                with self.subTest(source_id=source_id):
                    self.assertFalse(controller.connectDataSource(source_id))

        import_dialog.assert_not_called()
        self.assertEqual(controller._project, original_project)

        with patch.object(
            controller, "_import_sql_server_dialog", return_value=False
        ) as sql_server_import:
            self.assertFalse(controller.connectDataSource("microsoft_sql_server"))
        sql_server_import.assert_called_once_with()
        self.assertEqual(controller._project, original_project)

    def test_canceling_file_replacement_preserves_the_loaded_source(self) -> None:
        current_path = self.root / "current.csv"
        current_path.write_text("id\n1\n", encoding="utf-8")
        replacement_path = self.root / "replacement.csv"
        replacement_path.write_text("id\n2\n", encoding="utf-8")
        controller = self.new_controller()
        self.assertTrue(controller._commit_import(current_path, parse_file(current_path)))
        original_project = copy.deepcopy(controller._project)

        with patch.object(FileImportPreviewDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            committed = controller.import_data_path(replacement_path)

        self.assertFalse(committed)
        self.assertEqual(controller._project, original_project)
        self.assertEqual(controller._source_path, current_path.resolve())
        self.assertEqual(controller._rows, [{"id": "1"}])
        self.assertTrue(controller._dirty)

    def test_save_reopen_refresh_and_failed_refresh_preserve_last_good_rows(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("name;amount\nAda;12\n", encoding="utf-8")
        project_path = self.root / "sales.npa"
        controller = self.new_controller()
        candidate = parse_file(source_path, {"delimiter": ";"})

        self.assertTrue(controller._commit_import(source_path, candidate))
        self.assertTrue(controller._save_to(project_path))

        reopened = self.new_controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._active_parser_options["delimiter"], ";")
        self.assertEqual(reopened._rows, [{"name": "Ada", "amount": "12"}])

        source_path.write_text("name;amount\nAda;12\nLin;18\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened.rowCount, 2)

        reopened.add_page()
        last_good_rows = copy.deepcopy(reopened._rows)
        last_good_project = copy.deepcopy(reopened._project)
        dirty_before = reopened._dirty
        source_path.write_text('name;amount\n"unterminated;25\n', encoding="utf-8")
        with patch.object(QMessageBox, "critical"):
            reopened.refresh_source()

        self.assertEqual(reopened._rows, last_good_rows)
        self.assertEqual(reopened._project, last_good_project)
        self.assertEqual(reopened._dirty, dirty_before)
        self.assertIn("Could not refresh sales.csv", reopened.sourceWarning)

    def test_deep_json_parse_error_is_handled_on_refresh_and_project_open(self) -> None:
        source_path = self.root / "records.json"
        source_path.write_text('[{"id":1}]', encoding="utf-8")
        project_path = self.root / "records.npa"
        controller = self.new_controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        self.assertTrue(controller._save_to(project_path))
        good_rows = copy.deepcopy(controller._rows)
        good_project = copy.deepcopy(controller._project)
        source_path.write_text(
            "[" + "[" * 100_000 + "0" + "]" * 100_000 + "]",
            encoding="utf-8",
        )

        with patch.object(QMessageBox, "critical"):
            controller.refresh_source()

        self.assertEqual(controller._rows, good_rows)
        self.assertEqual(controller._project, good_project)
        self.assertIn("nesting exceeds", controller.sourceWarning)

        reopened = self.new_controller()
        with patch.object(QMessageBox, "warning"):
            self.assertTrue(reopened.open_project_path(project_path))

        self.assertFalse(reopened.sourceLoaded)
        self.assertIn("nesting exceeds", reopened.sourceWarning)


if __name__ == "__main__":
    unittest.main()
