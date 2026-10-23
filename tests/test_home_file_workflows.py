"""End-to-end controller checks for the Home and File data workflows."""

from __future__ import annotations

import copy
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QToolButton,
)

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.folder_import import default_folder_options, parse_folder
from analytics_studio.import_preview_dialog import FileImportPreviewDialog
from analytics_studio.inline_data import parse_pasted_table, sample_candidate
from analytics_studio.measure_dialog import MeasureDialog
from analytics_studio.local_table_dialogs import (
    CustomColumnDialog,
    EnterDataDialog,
    TransformDataDialog,
)
from analytics_studio.odata_dialog import ODataFeedImportDialog
from analytics_studio.sql_server_dialog import SQLServerImportDialog
from analytics_studio.power_query_m import PowerQueryMEditorDialog
from analytics_studio.project import FORMAT_VERSION
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import apply_transformations
from analytics_studio.web_import_dialog import WebImportDialog

QQuickStyle.setStyle("Basic")


class HomeFileWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def test_enter_data_dialog_previews_accepts_and_cancels_without_side_effects(self) -> None:
        dialog = EnterDataDialog(
            replacing=True,
            initial_text="Name\tRevenue\nAda\t12\nLin\t20",
        )
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 2)
        self.assertFalse(dialog.replacement_label.isHidden())

        dialog._accept_candidate()

        self.assertEqual(dialog.candidate.kind, "inline")
        self.assertEqual(dialog.candidate.headers, ["Name", "Revenue"])
        self.assertEqual(dialog.candidate.row_count, 2)

        canceled = EnterDataDialog(replacing=False, initial_text="Name\nAda")
        canceled.reject()
        self.assertIsNone(canceled.candidate)

    def test_inline_and_sample_tables_save_reopen_and_do_not_offer_refresh(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(sample_candidate()))
        self.assertTrue(controller.sourceLoaded)
        self.assertFalse(controller.canRefreshSource)
        self.assertEqual(controller._active_source_kind, "inline")
        self.assertEqual(controller.rowCount, sample_candidate().row_count)
        expected_rows = copy.deepcopy(controller._rows)

        path = self.root / "sample.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertTrue(reopened.sourceLoaded)
        self.assertFalse(reopened.canRefreshSource)
        self.assertEqual(reopened._rows, expected_rows)
        self.assertEqual(reopened._project["format_version"], FORMAT_VERSION)

        pasted = parse_pasted_table("Name,Revenue\nAda,12", name="Manual table")
        self.assertTrue(reopened._commit_inline(pasted))
        self.assertEqual(reopened.sourceName, "Manual table")
        self.assertFalse(reopened.canRefreshSource)

    def test_sample_data_is_deterministic(self) -> None:
        first = sample_candidate()
        second = sample_candidate()
        self.assertEqual(first, second)
        controller = self.controller()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(controller._commit_inline(first))
            self.assertTrue(controller._commit_inline(second))
        self.assertEqual(controller._rows, first.rows)

    def test_file_preview_uses_source_settings_language_for_query_edits(self) -> None:
        path = self.root / "settings.csv"
        path.write_text("Region,Revenue\nDubai,10\n", encoding="utf-8")
        dialog = FileImportPreviewDialog(
            path,
            replacing=False,
            source_editing=True,
            initial_options={"delimiter": ","},
        )
        self.assertEqual(dialog.windowTitle(), "Edit source settings")
        self.assertEqual(dialog.import_button.text(), "Apply settings")
        self.assertFalse(dialog.replacement_label.isVisible())
        self.assertTrue(dialog.transform_button.isHidden())
        dialog.reject()

    def test_file_preview_offers_load_or_transform_after_preview(self) -> None:
        path = self.root / "choice.csv"
        path.write_text("Region,Revenue\nDubai,10\n", encoding="utf-8")

        dialog = FileImportPreviewDialog(path, replacing=False)

        self.assertTrue(dialog.import_button.isEnabled())
        self.assertEqual(dialog.import_button.text(), "Load")
        self.assertFalse(dialog.transform_button.isHidden())
        self.assertTrue(dialog.transform_button.isEnabled())
        self.assertIsNone(dialog.selected_action)

        dialog._accept_candidate("transform")

        self.assertEqual(dialog.selected_action, "transform")
        self.assertEqual(dialog.candidate.headers, ["Region", "Revenue"])

    def test_file_preview_displays_excel_header_row_notice(self) -> None:
        path = self.root / "header-notice.csv"
        path.write_text("Date,Value\n2026-08-01,100\n", encoding="utf-8")
        dialog = FileImportPreviewDialog(path, replacing=False)
        notice = (
            "Using worksheet row 12 as column names; rows 1–11 are excluded "
            "from the imported table."
        )
        candidate = ImportCandidate(
            "excel",
            ["Date", "Value"],
            [{"Date": "2026-08-01", "Value": 100}],
            {"sheet_name": "VAT 5%", "header_row": 12},
            [notice],
        )

        dialog._show_preview_candidate(candidate)

        self.assertFalse(dialog.notice_label.isHidden())
        self.assertEqual(dialog.notice_label.text(), notice)
        dialog.reject()

    def test_remote_import_dialog_buttons_select_load_and_transform(self) -> None:
        sql_candidate = ImportCandidate(
            "sql_server", ["Id"], [{"Id": "1"}],
            {"schema": "dbo", "table_name": "Sales", "object_type": "table"}, [],
        )
        sql = SQLServerImportDialog()
        sql._candidate = sql_candidate
        sql._set_action_buttons_enabled(True)
        with (
            patch.object(sql, "_settings", return_value={
                "server": "localhost", "port": 1433,
                "database": "SalesDb", "username": "analyst", "driver": "ODBC",
            }),
            patch("analytics_studio.sql_server_dialog.read_sql_server_object", return_value=sql_candidate),
        ):
            sql.transform_button.click()
        self.assertEqual(sql.selected_action, "transform")

        odata_candidate = ImportCandidate(
            "odata", ["Id"], [{"Id": "1"}], {"entity_set_name": "Orders"}, [],
        )
        odata = ODataFeedImportDialog()
        odata._candidate = odata_candidate
        odata._set_action_buttons_enabled(True)
        with (
            patch.object(odata, "_root", return_value="https://example.test/odata/"),
            patch("analytics_studio.odata_dialog.read_odata_entity_set", return_value=odata_candidate),
        ):
            odata.import_button.click()
        self.assertEqual(odata.selected_action, "load")

        web_candidate = ImportCandidate(
            "web", ["Id"], [{"Id": "1"}],
            {"resource_type": "json", "json_path": "$.data"}, [],
        )
        web = WebImportDialog()
        web.url_edit.setText("https://example.test/data.json")
        web._candidate = web_candidate
        web._set_action_buttons_enabled(True)
        with patch("analytics_studio.web_import_dialog.read_web_source", return_value=web_candidate):
            web.transform_button.click()
        self.assertEqual(web.selected_action, "transform")

    def test_import_transform_stages_before_load_and_close_apply_commits(self) -> None:
        path = self.root / "staged.csv"
        path.write_text("Region,Revenue\nDubai,10\n", encoding="utf-8")
        controller = self.controller()
        project_before = copy.deepcopy(controller._project)

        def choose_transform(dialog: FileImportPreviewDialog) -> int:
            dialog._accept_candidate("transform")
            return QDialog.DialogCode.Accepted

        def close_and_apply(dialog: TransformDataDialog) -> int:
            self.assertEqual(len(dialog._query_states), 1)
            staged = next(iter(dialog._query_states.values()))
            self.assertTrue(staged["is_new_source"])
            self.assertFalse(controller.sourceLoaded)
            self.assertEqual(controller._project, project_before)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(FileImportPreviewDialog, "exec", new=choose_transform),
            patch.object(TransformDataDialog, "exec", new=close_and_apply),
        ):
            self.assertTrue(controller._import_file_path(path))

        self.assertTrue(controller.sourceLoaded)
        self.assertEqual(controller._rows, [{"Region": "Dubai", "Revenue": "10"}])
        self.assertEqual(len(controller._project["data_sources"]), 1)
        self.assertEqual(controller._project["data_sources"][0]["kind"], "csv")

    def test_cancel_transform_import_leaves_project_unmodified(self) -> None:
        path = self.root / "cancel-transform.csv"
        path.write_text("Region,Revenue\nDubai,10\n", encoding="utf-8")
        controller = self.controller()
        project_before = copy.deepcopy(controller._project)

        def choose_transform(dialog: FileImportPreviewDialog) -> int:
            dialog._accept_candidate("transform")
            return QDialog.DialogCode.Accepted

        with (
            patch.object(FileImportPreviewDialog, "exec", new=choose_transform),
            patch.object(TransformDataDialog, "exec", return_value=QDialog.DialogCode.Rejected),
        ):
            self.assertFalse(controller._import_file_path(path))

        self.assertFalse(controller.sourceLoaded)
        self.assertEqual(controller._project, project_before)
        self.assertFalse(controller.dirty)

    def test_transform_import_adds_to_existing_power_query_session(self) -> None:
        original_path = self.root / "existing.csv"
        original_path.write_text("Region,Revenue\nDubai,10\n", encoding="utf-8")
        imported_path = self.root / "new.csv"
        imported_path.write_text("Region,Revenue\nAbu Dhabi,20\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(original_path, parse_file(original_path)))
        existing_id = str(controller._active_source_id)
        project_before = copy.deepcopy(controller._project)

        def choose_transform(dialog: FileImportPreviewDialog) -> int:
            dialog._accept_candidate("transform")
            return QDialog.DialogCode.Accepted

        def close_and_apply(dialog: TransformDataDialog) -> int:
            self.assertIn(existing_id, dialog._query_states)
            staged_ids = {
                query_id for query_id, query in dialog._query_states.items()
                if query.get("is_new_source")
            }
            self.assertEqual(len(staged_ids), 1)
            self.assertEqual(controller._project, project_before)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch.object(FileImportPreviewDialog, "exec", new=choose_transform),
            patch.object(TransformDataDialog, "exec", new=close_and_apply),
        ):
            self.assertTrue(controller._import_file_path(imported_path))

        self.assertEqual(len(controller._project["data_sources"]), 2)
        self.assertNotEqual(controller._active_source_id, existing_id)
        self.assertEqual(controller._rows, [{"Region": "Abu Dhabi", "Revenue": "20"}])

    def test_non_file_importers_stage_transform_without_committing(self) -> None:
        controller = self.controller()
        cases = (
            (
                "analytics_studio.controller.SQLServerImportDialog",
                "_import_sql_server_dialog",
                ImportCandidate(
                    "sql_server", ["Id"], [{"Id": "1"}],
                    {"schema": "dbo", "table_name": "Sales", "object_type": "table"}, [],
                ),
                {
                    "connection_settings": {
                        "server": "localhost", "port": 1433,
                        "database": "SalesDb", "username": "analyst", "driver": "ODBC",
                    },
                    "password": "session-secret",
                },
                "sql_server",
            ),
            (
                "analytics_studio.controller.ODataFeedImportDialog",
                "_import_odata_dialog",
                ImportCandidate(
                    "odata", ["Id"], [{"Id": "1"}],
                    {"entity_set_name": "Orders"}, [],
                ),
                {"service_root": "https://example.test/odata/"},
                "odata",
            ),
            (
                "analytics_studio.controller.WebImportDialog",
                "_import_web_dialog",
                ImportCandidate(
                    "web", ["Id"], [{"Id": "1"}],
                    {"resource_type": "json", "json_path": "$.data"}, [],
                ),
                {"url": "https://example.test/data.json"},
                "web",
            ),
        )
        for dialog_path, import_method, candidate, accepted_values, expected_kind in cases:
            with self.subTest(kind=expected_kind):
                controller = self.controller()
                with patch(dialog_path) as dialog_type:
                    dialog = dialog_type.return_value
                    dialog.exec.return_value = QDialog.DialogCode.Accepted
                    dialog.candidate = candidate
                    dialog.selected_action = "transform"
                    for key, value in accepted_values.items():
                        setattr(dialog, key, value)
                    with patch.object(
                        controller, "transform_data_dialog", return_value=True
                    ) as transform:
                        self.assertTrue(getattr(controller, import_method)())

                pending_candidate, pending_source = transform.call_args.kwargs[
                    "pending_source"
                ]
                self.assertEqual(pending_candidate.kind, expected_kind)
                self.assertEqual(pending_source["kind"], expected_kind)
                self.assertEqual(controller._project["data_sources"], [])
                if expected_kind == "sql_server":
                    self.assertEqual(pending_source["_staged_password"], "session-secret")

    def test_folder_import_can_open_power_query_before_project_commit(self) -> None:
        folder = self.root / "monthly"
        folder.mkdir()
        controller = self.controller()
        candidate = ImportCandidate(
            "folder", ["Region"], [{"Region": "Dubai"}],
            {"file_kind": "csv", "recursive": False}, [],
        )

        with patch("analytics_studio.controller.FolderImportDialog") as dialog_type:
            dialog = dialog_type.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.candidate = candidate
            dialog.selected_action = "transform"
            with patch.object(
                controller, "transform_data_dialog", return_value=True
            ) as transform:
                self.assertTrue(controller._import_folder_path(folder))

        pending_candidate, pending_source = transform.call_args.kwargs[
            "pending_source"
        ]
        self.assertEqual(pending_candidate.kind, "folder")
        self.assertEqual(pending_source["path"], str(folder.resolve()))
        self.assertEqual(controller._project["data_sources"], [])

    def test_power_query_source_settings_reuses_connector_and_parser_options(self) -> None:
        controller = self.controller()
        original_path = self.root / "original.csv"
        original_path.write_text("Region,Revenue\nDubai,10\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(original_path, parse_file(original_path)))
        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller._active_source_id
        )
        replacement = self.root / "replacement.csv"
        replacement.write_text("Region;Revenue\nAbu Dhabi;20\n", encoding="utf-8")
        candidate = parse_file(replacement, options={"delimiter": ";"})

        with (
            patch(
                "analytics_studio.controller.QFileDialog.getOpenFileName",
                return_value=(str(replacement), ""),
            ),
            patch(
                "analytics_studio.import_preview_dialog.FileImportPreviewDialog"
            ) as preview_dialog,
        ):
            preview_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview_dialog.return_value.candidate = candidate
            result = controller._edit_power_query_source_candidate(source)

        self.assertIsNotNone(result)
        edited_candidate, edited_source = result
        self.assertEqual(edited_candidate, candidate)
        self.assertEqual(edited_source["id"], source["id"])
        self.assertEqual(edited_source["kind"], source["kind"])
        self.assertEqual(
            edited_source.get("query_name"), source.get("query_name")
        )
        self.assertEqual(edited_source["path"], str(replacement.resolve()))
        self.assertEqual(edited_source["parser_options"]["delimiter"], ";")
        preview_dialog.assert_called_once()
        self.assertEqual(
            preview_dialog.call_args.kwargs["initial_options"],
            source["parser_options"],
        )
        self.assertTrue(preview_dialog.call_args.kwargs["source_editing"])

    def test_power_query_source_settings_supports_sqlite_path_and_table_options(self) -> None:
        controller = self.controller()
        old_path = self.root / "old.sqlite"
        new_path = self.root / "new.sqlite"
        for path, rows in (
            (old_path, [("Dubai", "10")]),
            (new_path, [("Abu Dhabi", "20")]),
        ):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "CREATE TABLE Sales (Region TEXT, Amount TEXT)"
                )
                connection.executemany(
                    "INSERT INTO Sales VALUES (?, ?)", rows
                )
        original = {
            "id": "sales-source",
            "name": old_path.name,
            "query_name": "Sales",
            "kind": "sqlite",
            "path": str(old_path.resolve()),
            "parser_options": {"table_name": "Sales"},
            "transform_steps": [],
        }
        candidate = parse_file(new_path, options={"table_name": "Sales"})

        with (
            patch(
                "analytics_studio.controller.QFileDialog.getOpenFileName",
                return_value=(str(new_path), ""),
            ) as file_picker,
            patch(
                "analytics_studio.import_preview_dialog.FileImportPreviewDialog"
            ) as preview_dialog,
        ):
            preview_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview_dialog.return_value.candidate = candidate
            result = controller._edit_power_query_source_candidate(original)

        self.assertIsNotNone(result)
        edited_candidate, edited_source = result
        self.assertEqual(edited_candidate, candidate)
        self.assertEqual(edited_source["id"], original["id"])
        self.assertEqual(edited_source["kind"], "sqlite")
        self.assertEqual(edited_source["parser_options"], {"table_name": "Sales"})
        self.assertEqual(edited_source["path"], str(new_path.resolve()))
        self.assertIn("SQLite databases", file_picker.call_args.args[3])
        self.assertEqual(
            preview_dialog.call_args.kwargs["initial_options"],
            {"table_name": "Sales"},
        )
        self.assertTrue(preview_dialog.call_args.kwargs["source_editing"])

    def test_power_query_folder_source_settings_reuses_combine_recipe(self) -> None:
        controller = self.controller()
        old_folder = self.root / "old-monthly"
        new_folder = self.root / "new-monthly"
        old_folder.mkdir()
        new_folder.mkdir()
        (old_folder / "records.csv").write_text(
            "Region,Revenue\nDubai,10\n", encoding="utf-8"
        )
        (new_folder / "records.csv").write_text(
            "Region,Revenue\nAbu Dhabi,20\n", encoding="utf-8"
        )
        old_candidate = parse_folder(old_folder)
        self.assertTrue(controller._commit_import(old_folder, old_candidate))
        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller._active_source_id
        )
        new_options = default_folder_options()
        new_options.update(
            recursive=True,
            name_contains="records",
            sample_file="records.csv",
        )
        candidate = parse_folder(new_folder, new_options)

        with (
            patch(
                "analytics_studio.controller.QFileDialog.getExistingDirectory",
                return_value=str(new_folder),
            ) as folder_picker,
            patch("analytics_studio.controller.FolderImportDialog") as folder_dialog,
        ):
            folder_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            folder_dialog.return_value.candidate = candidate
            result = controller._edit_power_query_source_candidate(source)

        self.assertIsNotNone(result)
        edited_candidate, edited_source = result
        self.assertEqual(edited_candidate, candidate)
        self.assertEqual(edited_source["id"], source["id"])
        self.assertEqual(edited_source["kind"], "folder")
        self.assertEqual(edited_source["name"], source["name"])
        self.assertEqual(edited_source["path"], str(new_folder.resolve()))
        self.assertEqual(edited_source["parser_options"], candidate.options)
        folder_picker.assert_called_once()
        self.assertEqual(folder_dialog.call_args.args[0], new_folder.resolve())
        self.assertFalse(folder_dialog.call_args.kwargs["replacing"])
        self.assertTrue(folder_dialog.call_args.kwargs["source_editing"])
        self.assertEqual(
            folder_dialog.call_args.kwargs["initial_options"],
            source["parser_options"],
        )

    def test_sqlite_source_settings_preview_leaves_binding_check_to_session_apply(self) -> None:
        controller = self.controller()
        first_path = self.root / "first.sqlite"
        second_path = self.root / "second.sqlite"
        for path in (first_path, second_path):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE Sales (Region TEXT, Amount TEXT)")
                connection.execute("INSERT INTO Sales VALUES ('Dubai', '10')")
            candidate = parse_file(path, options={"table_name": "Sales"})
            self.assertTrue(controller._commit_import(path, candidate))
        first_source = next(
            item for item in controller._project["data_sources"]
            if item["path"] == str(first_path.resolve())
        )
        second_candidate = parse_file(
            second_path, options={"table_name": "Sales"}
        )

        with (
            patch(
                "analytics_studio.controller.QFileDialog.getOpenFileName",
                return_value=(str(second_path), ""),
            ),
            patch(
                "analytics_studio.import_preview_dialog.FileImportPreviewDialog"
            ) as preview_dialog,
            patch("analytics_studio.controller.QMessageBox.critical") as critical,
        ):
            preview_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview_dialog.return_value.candidate = second_candidate
            result = controller._edit_power_query_source_candidate(first_source)

        self.assertIsNotNone(result)
        edited_candidate, edited_source = result
        self.assertEqual(edited_candidate, second_candidate)
        self.assertEqual(edited_source["path"], str(second_path.resolve()))
        critical.assert_not_called()

    def test_home_commands_route_to_their_local_workflows(self) -> None:
        controller = self.controller()
        with (
            patch.object(controller, "enter_data_dialog") as enter,
            patch.object(controller, "load_sample_data") as sample,
            patch.object(controller, "transform_data_dialog") as transform,
            patch.object(controller, "power_query_m_editor_dialog") as power_query_m,
            patch.object(controller, "new_measure_dialog") as new_measure,
            patch.object(controller, "quick_measure_dialog") as quick_measure,
            patch.object(controller, "export_data_dialog") as export,
        ):
            controller.executeCommand("enterData")
            controller.executeCommand("pasteData")
            controller.executeCommand("sampleData")
            controller.executeCommand("transformData")
            controller.executeCommand("powerQueryM")
            controller.executeCommand("newMeasure")
            controller.executeCommand("quickMeasure")
            controller.executeCommand("exportData")

        enter.assert_any_call()
        enter.assert_any_call(use_clipboard=True)
        sample.assert_called_once_with()
        transform.assert_called_once_with()
        power_query_m.assert_called_once_with()
        new_measure.assert_called_once_with()
        quick_measure.assert_called_once_with()
        export.assert_called_once_with()

    def test_home_excel_command_opens_preview_before_staging_transform(self) -> None:
        controller = self.controller()
        workbook = self.root / "vat.xlsx"
        workbook.touch()
        candidate = ImportCandidate(
            "excel",
            ["Region", "Sales"],
            [{"Region": "Dubai", "Sales": 10}],
            {"sheet_name": "VAT 5%"},
            [],
        )

        self.addCleanup(self.app.processEvents)
        engine = QQmlEngine()
        self.addCleanup(engine.deleteLater)
        component = QQmlComponent(engine)
        self.addCleanup(component.deleteLater)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml")
        ))
        self.assertFalse(component.isError(), "\n".join(
            error.toString() for error in component.errors()
        ))
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(window, "\n".join(
            error.toString() for error in component.errors()
        ))
        assert window is not None
        self.addCleanup(window.deleteLater)
        excel_commands = {
            action["commandId"]
            for group in window.property("dataHomeGroups").toVariant()
            for action in group["actions"]
        }
        self.assertIn("data.importExcel", excel_commands)

        with (
            patch(
                "analytics_studio.controller.QFileDialog.getOpenFileName",
                return_value=(str(workbook), "Excel workbooks (*.xls *.xlsx *.xlsm)"),
            ) as picker,
            patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog") as preview,
            patch.object(controller, "transform_data_dialog", return_value=True) as transform,
        ):
            preview.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview.return_value.candidate = candidate
            preview.return_value.selected_action = "transform"
            window.runCommand("data.importExcel")

        picker.assert_called_once()
        self.assertIn("Excel workbooks", picker.call_args.args[3])
        preview.assert_called_once()
        self.assertEqual(preview.call_args.args[0], workbook.resolve())
        self.assertFalse(preview.call_args.kwargs["replacing"])
        transform.assert_called_once()
        staged_candidate, staged_source = transform.call_args.kwargs["pending_source"]
        self.assertEqual(staged_candidate, candidate)
        self.assertEqual(staged_source["kind"], "excel")
        self.assertEqual(staged_source["query_name"], "VAT 5%")
        self.assertFalse(controller.sourceLoaded)

    def test_transform_data_qml_command_reaches_dialog_and_commits_step(self) -> None:
        controller = self.controller()
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml")
        ))
        self.assertFalse(component.isError(), "\n".join(
            error.toString() for error in component.errors()
        ))
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(window, "\n".join(
            error.toString() for error in component.errors()
        ))

        unavailable_commands = (
            "security.manageRoles",
            "security.viewAs",
            "service.publish",
            "view.mobileLayout",
            "ai.qa",
        )
        for command_id in unavailable_commands:
            self.assertFalse(window.commandAvailable(command_id), command_id)
            self.assertTrue(window.commandUnavailableReason(command_id), command_id)

        controller.setCurrentView("Data")
        self.app.processEvents()
        self.assertFalse(window.commandAvailable("data.transform"))
        self.assertFalse(window.commandAvailable("data.newMeasure"))
        self.assertFalse(window.commandAvailable("data.powerQueryM"))
        self.assertFalse(window.commandAvailable("data.appendQueries"))
        self.assertFalse(window.commandAvailable("data.mergeQueries"))
        self.assertEqual(
            window.commandUnavailableReason("data.transform"),
            "Load a table before transforming data.",
        )
        self.assertIn("Load a table", window.commandUnavailableReason("data.newMeasure"))
        self.assertIn("Load a table", window.commandUnavailableReason("data.powerQueryM"))
        data_home_groups = window.property("dataHomeGroups").toVariant()
        home_command_ids = {
            action["commandId"]
            for group in data_home_groups
            for action in group["actions"]
        }
        self.assertIn("data.newMeasure", home_command_ids)
        self.assertIn("data.powerQueryM", home_command_ids)
        self.assertIn("data.appendQueries", home_command_ids)
        self.assertIn("data.mergeQueries", home_command_ids)

        source = self.root / "regions.csv"
        source.write_text("Region,Revenue\n East ,12\n West ,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        self.assertEqual(controller.activePageVisuals, [])
        self.app.processEvents()
        self.assertTrue(window.commandAvailable("data.transform"))
        self.assertTrue(window.commandAvailable("data.newMeasure"))
        self.assertTrue(window.commandAvailable("data.powerQueryM"))
        self.assertFalse(window.commandAvailable("data.appendQueries"))
        self.assertFalse(window.commandAvailable("data.mergeQueries"))
        self.assertEqual(window.commandUnavailableReason("data.transform"), "")
        with patch.object(controller, "new_measure_dialog") as new_measure:
            window.runCommand("data.newMeasure")
        new_measure.assert_called_once_with()
        with patch.object(controller, "power_query_m_editor_dialog") as m_editor:
            window.runCommand("data.powerQueryM")
        m_editor.assert_called_once_with()
        with (
            patch.object(controller, "append_queries_dialog") as append_queries,
            patch.object(controller, "merge_queries_dialog") as merge_queries,
        ):
            window.runCommand("data.appendQueries")
            window.runCommand("data.mergeQueries")
        append_queries.assert_called_once_with()
        merge_queries.assert_called_once_with()

        self.assertTrue(window.commandAvailable("model.newCalculatedTable"))
        with patch.object(controller, "calculated_table_dialog") as calculated_table:
            window.runCommand("model.newCalculatedTable")
        calculated_table.assert_called_once_with()
        transform_button = window.findChild(QObject, "transformDataButton")
        self.assertIsNotNone(transform_button)
        self.assertTrue(transform_button.property("visible"))
        with patch.object(controller, "transform_data_dialog") as transform:
            transform_button.click()
        transform.assert_called_once_with()

        def accept_trim_step(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("trim_text")
            )
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_trim_step):
            window.runCommand("data.transform")

        self.assertEqual(controller._rows, [
            {"Region": "East", "Revenue": "12"},
            {"Region": "West", "Revenue": "20"},
        ])
        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller.activeTableId
        )
        self.assertEqual(source_record["transform_steps"], [
            {"op": "trim_text", "column": "Region"},
        ])

        project = self.root / "transformed.npa"
        self.assertTrue(controller._save_to(project))
        source.write_text(
            "Region,Revenue\n East ,12\n West ,20\n North ,30\n", encoding="utf-8"
        )
        reopened = StudioController(
            self.app,
            QSettings(str(self.root / "reopened-settings.ini"), QSettings.Format.IniFormat),
        )
        self.assertTrue(reopened.open_project_path(project))
        self.assertEqual(reopened._rows, [
            {"Region": "East", "Revenue": "12"},
            {"Region": "West", "Revenue": "20"},
            {"Region": "North", "Revenue": "30"},
        ])

        window.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_power_query_m_editor_applies_and_persists_query_steps(self) -> None:
        controller = self.controller()
        source = self.root / "regions.csv"
        source.write_text("Region,Revenue\n East ,12\nWest,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        authored_script = '''// Keep this annotation with the query.
let
    Source = #"regions",
    // Normalize imported whitespace before filtering.
    NormalizedRegion = Table.TransformColumns(Source, {{"Region", Text.Trim, type text}}),
    EastOnly = Table.SelectRows(NormalizedRegion, each [Region] = "East")
in
    EastOnly'''

        def accept_filter(dialog: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            dialog.editor.setPlainText(authored_script)
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        with patch.object(PowerQueryMEditorDialog, "exec", new=accept_filter):
            self.assertTrue(controller.power_query_m_editor_dialog())

        self.assertEqual(controller._rows, [{"Region": "East", "Revenue": "12"}])
        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller.activeTableId
        )
        self.assertEqual(source_record["transform_steps"], [
            {"op": "trim_text", "column": "Region"},
            {"op": "filter_rows", "column": "Region", "operator": "equals", "value": "East"},
        ])
        self.assertEqual(source_record["m_script"], authored_script)

        project = self.root / "authored-query.npa"
        self.assertTrue(controller._save_to(project))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == reopened.activeTableId
        )
        self.assertEqual(reopened_source["m_script"], authored_script)

        def accept_restored_script(dialog: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            self.assertEqual(dialog.editor.toPlainText(), authored_script)
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        with patch.object(PowerQueryMEditorDialog, "exec", new=accept_restored_script):
            self.assertTrue(reopened.power_query_m_editor_dialog())

        source.write_text(
            "Region,Revenue\n East ,12\n East ,99\nWest,20\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Region": "East", "Revenue": "12"},
            {"Region": "East", "Revenue": "99"},
        ])
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == reopened.activeTableId
        )
        self.assertEqual(reopened_source["m_script"], authored_script)

    def test_direct_m_editor_route_opens_keep_duplicates_and_cancel_is_atomic(self) -> None:
        controller = self.controller()
        source = self.root / "regions.csv"
        source.write_text("Region,Revenue\nEast,12\nWest,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller.activeTableId
        )
        source_record["transform_steps"] = [
            {
                "op": "convert_type_using_locale", "column": "Revenue",
                "type": "decimal_number", "culture": "en-US",
            },
            {"op": "keep_duplicates", "columns": ["Region"]},
        ]
        project_before = copy.deepcopy(controller._project)
        rows_before = copy.deepcopy(controller._rows)

        with (
            patch("analytics_studio.controller.PowerQueryMEditorDialog") as editor,
            patch.object(QMessageBox, "critical") as critical,
        ):
            editor.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.assertFalse(controller.power_query_m_editor_dialog())

        editor.assert_called_once()
        critical.assert_not_called()
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._rows, rows_before)

    def test_power_query_session_restores_and_saves_authored_m_text(self) -> None:
        controller = self.controller()
        source = self.root / "regions.csv"
        source.write_text("Region\n East \nWest\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        original_script = '''let
    Source = #"regions",
    Cleaned = Table.TransformColumns(Source, {{"Region", Text.Trim, type text}})
in
    Cleaned'''

        def accept_original(dialog: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            dialog.editor.setPlainText(original_script)
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        with patch.object(PowerQueryMEditorDialog, "exec", new=accept_original):
            self.assertTrue(controller.power_query_m_editor_dialog())

        updated_script = "// Keep this note in the session editor.\n" + original_script

        def accept_updated(dialog: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            self.assertEqual(dialog.editor.toPlainText(), original_script)
            dialog.editor.setPlainText(updated_script)
            dialog._accept_query()
            return QDialog.DialogCode.Accepted

        def accept_session(dialog: TransformDataDialog) -> QDialog.DialogCode:
            with patch.object(PowerQueryMEditorDialog, "exec", new=accept_updated):
                dialog._open_advanced_editor()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_session):
            self.assertTrue(controller.transform_data_dialog())

        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == controller.activeTableId
        )
        self.assertEqual(source_record["m_script"], updated_script)

    def test_home_advanced_editor_stages_selected_query_until_session_apply(self) -> None:
        controller = self.controller()
        regions = self.root / "regions.csv"
        regions.write_text("Region,Revenue\n East ,12\nWest,20\n", encoding="utf-8")
        customers = self.root / "customers.csv"
        customers.write_text("Customer,Revenue\nAda,4\nLin,5\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(regions, parse_file(regions)))
        regions_id = controller._active_source_id
        self.assertTrue(controller._commit_import(customers, parse_file(customers)))
        self.assertNotEqual(controller._active_source_id, regions_id)
        script = '''let
    Source = #"regions",
    Cleaned = Table.TransformColumns(Source, {{"Region", Text.Trim, type text}})
in
    Cleaned'''
        before_cancel_project = copy.deepcopy(controller._project)
        before_cancel_rows = copy.deepcopy(controller._loaded_candidates)

        def stage_from_home(
            session: TransformDataDialog, *, accept_outer: bool
        ) -> QDialog.DialogCode:
            target_row = session._query_order.index(str(regions_id))
            self.assertNotEqual(target_row, session.query_list.currentRow())
            session.query_list.setCurrentRow(target_row)
            self.assertEqual(session._active_query_id, regions_id)
            button = session.findChild(QToolButton, "openPowerQueryMEditorHomeButton")
            self.assertIsNotNone(button)

            def accept_m(editor: PowerQueryMEditorDialog) -> QDialog.DialogCode:
                self.assertEqual(editor._query_name, "regions")
                self.assertEqual(editor._source_candidate, session._source_candidate)
                self.assertEqual(editor._steps, session._steps)
                editor.editor.setPlainText(script)
                editor._accept_query()
                return editor.result()

            with patch.object(PowerQueryMEditorDialog, "exec", new=accept_m):
                button.click()

            self.assertEqual(session._steps, [{"op": "trim_text", "column": "Region"}])
            self.assertEqual(
                [row["Region"] for row in session._preview_candidate.rows],
                ["East", "West"],
            )
            if accept_outer:
                session._accept_candidate()
                return QDialog.DialogCode.Accepted
            session.reject()
            return QDialog.DialogCode.Rejected

        with patch.object(
            TransformDataDialog,
            "exec",
            new=lambda session: stage_from_home(session, accept_outer=False),
        ):
            self.assertFalse(controller.transform_data_dialog())
        self.assertEqual(controller._project, before_cancel_project)
        self.assertEqual(controller._loaded_candidates, before_cancel_rows)

        with patch.object(
            TransformDataDialog,
            "exec",
            new=lambda session: stage_from_home(session, accept_outer=True),
        ):
            self.assertTrue(controller.transform_data_dialog())

        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == regions_id
        )
        self.assertEqual(source_record["transform_steps"], [
            {"op": "trim_text", "column": "Region"},
        ])
        self.assertEqual(source_record["m_script"], script)
        self.assertEqual(
            controller._loaded_candidates[regions_id].rows,
            [{"Region": "East", "Revenue": "12"}, {"Region": "West", "Revenue": "20"}],
        )

    def test_invalid_m_edit_after_preview_cannot_commit_through_controller(self) -> None:
        controller = self.controller()
        source = self.root / "regions.csv"
        source.write_text("Region,Revenue\nEast,12\nWest,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        project_before = copy.deepcopy(controller._project)
        rows_before = copy.deepcopy(controller._rows)
        dirty_before = controller._dirty

        def edit_then_break_query(dialog: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            dialog.editor.setPlainText('''let
    Source = #"regions",
    Trimmed = Table.TransformColumns(Source, {{"Region", Text.Trim, type text}})
in
    Trimmed''')
            dialog._preview_query()
            self.assertTrue(dialog.apply_button.isEnabled())
            dialog.editor.setPlainText('''let
    Source = #"wrong query"
in
    Source''')
            dialog._accept_query()
            return dialog.result()

        with patch.object(PowerQueryMEditorDialog, "exec", new=edit_then_break_query):
            self.assertFalse(controller.power_query_m_editor_dialog())

        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller._dirty, dirty_before)

    def test_model_view_exposes_dax_measure_editor_after_import(self) -> None:
        controller = self.controller()
        source = self.root / "sales.csv"
        source.write_text("Region,Revenue\nEast,12\nWest,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        self.assertTrue(controller.create_measure("Revenue total", "SUM([Revenue])"))
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml")
        ))
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(window, "\n".join(
            error.toString() for error in component.errors()
        ))
        window.show()
        controller.setCurrentView("Model")
        self.app.processEvents()
        dax_button = window.findChild(QObject, "newDaxMeasureButton")
        self.assertIsNotNone(dax_button)
        self.assertTrue(dax_button.property("enabled"))

        with patch.object(controller, "new_measure_dialog") as new_measure:
            dax_button.click()
        new_measure.assert_called_once_with()

        measure_list = window.findChild(QObject, "daxMeasureList")
        self.assertIsNotNone(measure_list)
        measure_delegate = measure_list.property("currentItem")
        self.assertIsNotNone(measure_delegate)
        edit_button = measure_delegate.findChild(QObject, "editDaxMeasureButton")
        delete_button = measure_delegate.findChild(QObject, "deleteDaxMeasureButton")
        self.assertIsNotNone(edit_button)
        self.assertIsNotNone(delete_button)
        with patch.object(controller, "editMeasure", return_value=True) as edit_measure:
            edit_button.click()
        edit_measure.assert_called_once_with("Revenue total")
        with (
            patch("analytics_studio.controller.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
            patch.object(controller, "remove_measure", return_value=True) as remove_measure,
        ):
            delete_button.click()
        remove_measure.assert_called_once_with("Revenue total")

        window.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_view_new_measure_command_creates_extrema_and_recomputes(self) -> None:
        controller = self.controller()
        source = self.root / "sales.csv"
        source.write_text("Region,Revenue\nEast,12\nWest,20\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(source, parse_file(source)))

        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml")
        ))
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(window, "\n".join(
            error.toString() for error in component.errors()
        ))
        window.show()
        controller.setCurrentView("Model")
        self.app.processEvents()
        dax_button = window.findChild(QObject, "newDaxMeasureButton")
        self.assertIsNotNone(dax_button)
        assert dax_button is not None

        measures = iter((
            ("Highest revenue", "MAXX", "20"),
            ("Lowest revenue", "MINX", "12"),
        ))

        def accept_extreme(dialog: MeasureDialog) -> int:
            measure_name, function, expected = next(measures)
            expression = f"{function}('sales', [Revenue])"
            dialog.name_edit.setText(measure_name)
            dialog.expression_edit.setPlainText(expression)
            dialog.preview_button.click()
            self.assertEqual(
                dialog.preview_label.text(),
                f"Current report-context result: {expected}",
            )
            dialog.save_button.click()
            self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
            return dialog.result()

        with patch.object(MeasureDialog, "exec", new=accept_extreme):
            dax_button.click()
            dax_button.click()

        saved_measures = {
            measure["name"]: measure for measure in controller.modelMeasures
            if measure["name"] in {"Highest revenue", "Lowest revenue"}
        }
        self.assertEqual(
            saved_measures["Highest revenue"]["expression"],
            "MAXX('sales', [Revenue])",
        )
        self.assertEqual(saved_measures["Highest revenue"]["value"], "20")
        self.assertEqual(
            saved_measures["Lowest revenue"]["expression"],
            "MINX('sales', [Revenue])",
        )
        self.assertEqual(saved_measures["Lowest revenue"]["value"], "12")

        controller.add_visual("card", "Highest revenue card", 20, 20, 150, 90)
        controller.add_field_to_well(
            "Fields", "__dax_measure__:Highest revenue"
        )
        controller.add_visual("card", "Lowest revenue card", 190, 20, 150, 90)
        controller.add_field_to_well(
            "Fields", "__dax_measure__:Lowest revenue"
        )
        self.assertEqual(
            controller.visualCardData("Highest revenue card")["value"], "20"
        )
        self.assertEqual(
            controller.visualCardData("Lowest revenue card")["value"], "12"
        )
        project_path = self.root / "model-view-maxx.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Highest revenue"], "20")
        self.assertEqual(reopened.reportKpis["Lowest revenue"], "12")
        self.assertEqual(
            reopened.visualCardData("Highest revenue card")["value"], "20"
        )
        self.assertEqual(
            reopened.visualCardData("Lowest revenue card")["value"], "12"
        )
        source.write_text(
            "Region,Revenue\nEast,4\nWest,25\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened.reportKpis["Highest revenue"], "25")
        self.assertEqual(reopened.reportKpis["Lowest revenue"], "4")
        self.assertEqual(
            reopened.visualCardData("Highest revenue card")["value"], "25"
        )
        self.assertEqual(
            reopened.visualCardData("Lowest revenue card")["value"], "4"
        )

        window.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_table_card_opens_selected_table_in_data_view(self) -> None:
        controller = self.controller()
        first = self.root / "region_sales.csv"
        first.write_text("Region,Revenue\nEast,12\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(first, parse_file(first)))
        first_id = controller.activeTableId
        second = self.root / "item_stock.csv"
        second.write_text("Item,Quantity\nPens,4\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(second, parse_file(second)))
        self.assertNotEqual(controller.activeTableId, first_id)
        first_table = next(
            table for table in controller.tableCatalog
            if table["sourceId"] == first_id
        )
        second_table = next(
            table for table in controller.tableCatalog
            if table["sourceId"] == controller.activeTableId
        )
        controller._project["model"]["relationships"] = [{
            "relationship_version": 1,
            "id": "items-to-regions",
            "from": "Items[Item]",
            "to": "Region Sales[Region]",
            "from_table_id": second_table["id"],
            "from_column": "Item",
            "to_table_id": first_table["id"],
            "to_column": "Region",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(
            str(Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml")
        ))
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(window, "\n".join(
            error.toString() for error in component.errors()
        ))
        window.show()
        def cleanup_main_window() -> None:
            # Imported test data marks the controller dirty. Keep teardown from
            # opening the real Save/Discard/Cancel prompt in the offscreen UI.
            controller._dirty = False
            window.close()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_main_window)

        def visual_descendants(item: QObject) -> list[QObject]:
            descendants: list[QObject] = []
            for child in item.childItems():
                descendants.append(child)
                descendants.extend(visual_descendants(child))
            return descendants

        window_items = visual_descendants(window.contentItem())
        data_navigation = next(
            (item for item in window_items if item.objectName() == "workspaceNavigationButton_Data"),
            None,
        )
        model_navigation = next(
            (item for item in window_items if item.objectName() == "workspaceNavigationButton_Model"),
            None,
        )
        self.assertIsNotNone(data_navigation)
        self.assertIsNotNone(model_navigation)
        self.assertTrue(data_navigation.isVisible())
        self.assertTrue(data_navigation.isEnabled())
        self.assertTrue(model_navigation.isVisible())
        self.assertTrue(model_navigation.isEnabled())
        data_navigation.click()
        self.assertEqual(controller.currentView, "Data")
        model_navigation.click()
        self.assertEqual(controller.currentView, "Model")
        self.app.processEvents()

        model_diagram = window.findChild(QObject, "modelRelationshipDiagram")
        model_view = window.findChild(QObject, "modelViewRoot")
        model_toggle = window.findChild(QObject, "toggleModelDiagramButton")
        self.assertIsNotNone(model_diagram)
        self.assertIsNotNone(model_view)
        self.assertIsNotNone(model_toggle)
        self.assertTrue(model_diagram.property("visible"))
        self.assertEqual(len(model_view.property("diagramNodes").toVariant()), 2)
        self.assertEqual(len(model_view.property("diagramRelationshipRoutes").toVariant()), 1)
        relationship_link = next(
            item for item in visual_descendants(model_diagram)
            if item.objectName() == "modelDiagramRelationshipLink_items-to-regions"
        )
        self.assertTrue(relationship_link.isVisible())
        relationship_link.click()
        self.assertEqual(
            str(model_view.property("selectedModelTableId")), str(second_table["id"])
        )
        self.assertEqual(str(model_view.property("selectedModelColumn")), "Item")
        model_toggle.click()
        self.assertFalse(model_diagram.property("visible"))

        target_id = controller.tableCatalog[0]["sourceId"]
        table_cards = window.findChild(QObject, "modelTableCardsFlow")
        self.assertIsNotNone(table_cards)

        table_buttons = [
            item for item in visual_descendants(table_cards)
            if item.objectName() == "openModelTableDataButton"
        ]
        self.assertEqual(len(table_buttons), 2)
        for button in table_buttons:
            self.assertTrue(button.property("enabled"))
        target_button = next(
            button for button in table_buttons
            if button.property("tableSourceId") == target_id
        )
        target_headers = next(
            table["headers"]
            for table in controller.tableCatalog
            if table["sourceId"] == target_id
        )

        with patch.object(controller, "selectTable", return_value=False) as select_table:
            target_button.click()
        select_table.assert_called_once_with(target_id)
        self.assertEqual(controller.currentView, "Model")

        target_button.click()
        self.assertEqual(controller.activeTableId, target_id)
        self.assertEqual(controller.currentView, "Data")
        self.assertEqual(controller.headers, target_headers)
        self.assertIsNotNone(window.findChild(QObject, "dataViewTable"))

    def test_transform_dialog_previews_step_order_and_returns_only_after_accept(self) -> None:
        raw = parse_pasted_table("Region,Revenue\nEast,12\nWest,20")
        dialog = TransformDataDialog(raw)
        self.assertEqual(dialog.windowTitle(), "Current Query - Power Query Editor")
        self.assertIn("Power Query M", dialog.advanced_editor_button.toolTip())
        self.assertIsNotNone(dialog.findChild(QObject, "openPowerQueryMEditorButton"))
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Revenue")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("whole_number")
        )
        dialog._add_step()

        self.assertEqual(dialog.preview.model().data(dialog.preview.model().index(0, 1)), "12")
        self.assertEqual(dialog.step_list.count(), 1)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("rename_column")
        )
        dialog.column_combo.setCurrentText("Revenue")
        dialog.value_edit.setText("Sales")
        dialog._add_step()
        self.assertIn("Sales", dialog._preview_candidate.headers)
        dialog._remove_step()
        self.assertIn("Revenue", dialog._preview_candidate.headers)
        dialog._accept_candidate()
        self.assertEqual(
            dialog.steps,
            [{"op": "convert_type", "column": "Revenue", "type": "whole_number"}],
        )
        self.assertEqual(dialog.candidate.rows[0]["Revenue"], 12)

        canceled = TransformDataDialog(raw)
        canceled.reject()
        self.assertIsNone(canceled.candidate)
        self.assertIsNone(canceled.steps)

    def test_transform_ribbon_detects_safe_column_types_as_steps(self) -> None:
        raw = parse_pasted_table(
            "Date,Transaction ID,Quantity,Value\n"
            "2026-08-01,000123,75,4500.5\n"
            "2026-08-02,000124,100,1150",
        )
        dialog = TransformDataDialog(raw)
        detect_button = dialog.findChild(QToolButton, "powerQueryDetectDataTypesButton")

        self.assertIsNotNone(detect_button)
        detect_button.click()

        self.assertEqual(dialog._steps, [
            {"op": "convert_type", "column": "Date", "type": "date"},
            {"op": "convert_type", "column": "Quantity", "type": "whole_number"},
            {"op": "convert_type", "column": "Value", "type": "decimal_number"},
        ])
        self.assertEqual(dialog._preview_candidate.rows[0]["Transaction ID"], "000123")

    def test_import_detects_dates_and_measures_but_keeps_identifiers_as_text(self) -> None:
        source = self.root / "vat-import.csv"
        source.write_text(
            "Date,TRN,Quantity,Value\n"
            "2026-08-01,100233708500003,75,4500.5\n"
            "2026-08-02,100108694000003,100,1150",
            encoding="utf-8",
        )
        controller = self.controller()

        self.assertTrue(controller._commit_import(source, parse_file(source)))
        loaded_table = next(
            table for table in controller._project["model"]["tables"]
            if table.get("source_id") == controller._active_source_id
        )
        self.assertEqual(loaded_table["column_types"], {
            "Date": "date",
            "TRN": "text",
            "Quantity": "whole_number",
            "Value": "decimal_number",
        })

        project_path = self.root / "typed-import.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_table = next(
            table for table in reopened._project["model"]["tables"]
            if table.get("source_id") == reopened._active_source_id
        )
        self.assertEqual(reopened_table["column_types"], loaded_table["column_types"])

        source.write_text(
            "Date,TRN,Quantity,Value\n"
            "2026-08-03,100233708500003,2,20.25",
            encoding="utf-8",
        )
        reopened.refresh_source()
        refreshed_table = next(
            table for table in reopened._project["model"]["tables"]
            if table.get("source_id") == reopened._active_source_id
        )
        self.assertEqual(refreshed_table["column_types"], loaded_table["column_types"])
        self.assertEqual(reopened._rows[0]["Value"], "20.25")

    def test_power_query_ribbon_routes_all_transforms_and_view_controls(self) -> None:
        raw = parse_pasted_table("Region,Revenue\nEast,12\nWest,20")
        dialog = TransformDataDialog(raw)
        self.assertEqual(
            [dialog.ribbon_tabs.tabText(index) for index in range(dialog.ribbon_tabs.count())],
            ["Home", "Transform", "Add Column", "View", "Tools", "Help"],
        )
        operations = {
            str(dialog.operation_combo.itemData(index))
            for index in range(dialog.operation_combo.count())
        }
        self.assertEqual(set(dialog.ribbon_command_buttons), operations)
        direct_operations = (
            dialog._SELECTION_OPERATIONS_PER_COLUMN
            | dialog._SELECTION_OPERATIONS_COLUMN_LIST
            | dialog._PARAMETERLESS_OPERATIONS
            | {"remove_duplicates"}
        )

        for operation, button in dialog.ribbon_command_buttons.items():
            with self.subTest(operation=operation):
                self.assertIsNotNone(button)
                if operation not in dialog._STEP_OPERATIONS_WITHOUT_SETTINGS:
                    if operation == "add_custom_column":
                        previous_operation = dialog.operation_combo.currentData()

                        def accept_column(editor: CustomColumnDialog) -> int:
                            self.assertEqual(
                                [editor.column_list.item(index).text()
                                 for index in range(editor.column_list.count())],
                                ["Region", "Revenue"],
                            )
                            editor.reject()
                            return editor.result()

                        with patch.object(
                            CustomColumnDialog, "exec", new=accept_column
                        ):
                            button.click()
                        self.assertEqual(
                            dialog.operation_combo.currentData(), previous_operation
                        )
                        self.assertEqual(dialog.step_list.count(), 0)
                    elif operation == "conditional_column":
                        button.click()
                        self.assertIsNotNone(dialog._conditional_dialog)
                        dialog._conditional_dialog.reject()
                    elif operation in direct_operations:
                        # Power BI applies these immediately from the selected column.
                        fresh = TransformDataDialog(raw)
                        fresh.preview.selectColumn(1)
                        fresh.preview.setCurrentIndex(fresh.preview.model().index(0, 1))
                        fresh.ribbon_command_buttons[operation].click()
                        self.assertEqual(len(fresh._steps), 1)
                        self.assertEqual(fresh._steps[0]["op"], operation)
                        self.assertTrue(fresh.operation_settings_panel.isHidden())
                        fresh.deleteLater()
                    else:
                        button.click()
                        parameter_dialog = dialog._operation_dialog
                        self.assertIsNotNone(parameter_dialog)
                        self.assertEqual(dialog.operation_combo.currentData(), operation)
                        self.assertEqual(dialog.step_list.count(), 0)
                        parameter_dialog.reject()

        dialog.ribbon_tabs.setCurrentIndex(3)
        schema_button = next(
            button for button in dialog.ribbon_tabs.currentWidget().findChildren(QToolButton)
            if " ".join(button.text().split()).casefold() == "schema view"
        )
        schema_button.click()
        self.assertIs(dialog.preview_tabs.currentWidget(), dialog.schema_table)
        self.assertEqual(dialog.schema_table.rowCount(), 2)
        self.assertEqual(dialog.schema_table.item(0, 1).text(), "Region")
        self.assertEqual(dialog.schema_table.item(0, 2).text(), "text")
        self.assertEqual(dialog.schema_table.item(0, 3).text(), "East, West")

        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, 1))
        dialog.ribbon_command_buttons["uppercase_text"].click()
        self.assertEqual(dialog._steps[-1], {"op": "uppercase_text", "column": "Revenue"})
        self.assertTrue(dialog.operation_settings_panel.isHidden())

        preview_toggle = next(
            button for button in dialog.ribbon_tabs.currentWidget().findChildren(QToolButton)
            if " ".join(button.text().split()).casefold() == "data preview"
        )
        preview_toggle.click()
        self.assertTrue(dialog.preview.isHidden())
        preview_toggle.click()
        self.assertFalse(dialog.preview.isHidden())

        steps_toggle = next(
            button for button in dialog.ribbon_tabs.currentWidget().findChildren(QToolButton)
            if button.objectName() == "powerQueryQuerySettingsToggleButton"
        )
        steps_toggle.click()
        self.assertTrue(dialog.settings_steps_pane.isHidden())
        steps_toggle.click()
        self.assertFalse(dialog.settings_steps_pane.isHidden())

        self.assertEqual(dialog.advanced_editor_button.objectName(), "openPowerQueryMEditorButton")
        self.assertIn(dialog.advanced_editor_button, dialog.ribbon_tabs.currentWidget().findChildren(QToolButton))
        with patch.object(TransformDataDialog, "_open_advanced_editor") as open_editor:
            dialog.advanced_editor_button.click()
            open_editor.assert_called_once_with()

        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, 1))
        dialog.ribbon_command_buttons["trim_text"].click()
        self.assertEqual(dialog._steps[-1], {"op": "trim_text", "column": "Revenue"})
        # The Tools tab's Add Step still adds a step from the settings form.
        dialog.step_list.setCurrentRow(-1)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("lowercase_text"))
        dialog.column_combo.setCurrentText("Revenue")
        dialog.ribbon_tabs.setCurrentIndex(4)
        add_step = next(
            button for button in dialog.ribbon_tabs.currentWidget().findChildren(QToolButton)
            if " ".join(button.text().split()).casefold() == "add step"
        )
        add_step.click()
        self.assertEqual(dialog._steps[-1], {"op": "lowercase_text", "column": "Revenue"})

    def test_power_query_count_rows_applies_saves_reopens_and_refreshes(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Name\nAda\nLin\nMo\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        source_id = controller._active_source_id

        def accept_count_rows(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.ribbon_command_buttons["count_rows"].click()
            self.assertEqual(dialog._preview_candidate.rows, [{"Count": 3}])
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_count_rows):
            self.assertTrue(controller.transform_data_dialog())

        self.assertEqual(controller._rows, [{"Count": 3}])
        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(source_record["transform_steps"], [{"op": "count_rows"}])
        table = next(
            item for item in controller._project["model"]["tables"]
            if item.get("source_id") == source_id
        )
        self.assertEqual(table["column_types"], {"Count": "whole_number"})

        project_path = self.root / "count-rows.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{"Count": 3}])

        source.write_text("Name\nAda\nLin\nMo\nKai\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"Count": 4}])

    def test_power_query_session_applies_independent_queries_as_one_transaction(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region,Revenue\n East ,12", name="Sales")
        ))
        sales_id = controller._active_source_id
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Customer,Note\nAda,  account  ", name="Customers")
        ))
        customers_id = controller._active_source_id

        def accept_edits(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[sales_id])
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog.query_list.setCurrentRow(rows_by_id[customers_id])
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Note")
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_edits):
            self.assertTrue(controller.transform_data_dialog())

        sources = {source["id"]: source for source in controller._project["data_sources"]}
        self.assertEqual(sources[sales_id]["transform_steps"], [
            {"op": "trim_text", "column": "Region"},
        ])
        self.assertEqual(sources[customers_id]["transform_steps"], [
            {"op": "trim_text", "column": "Note"},
        ])
        self.assertEqual(controller._rows[0]["Note"], "account")

    def test_power_query_apply_refreshes_active_preview_without_step_edits(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Region\nEast\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        source_id = controller._active_source_id
        source.write_text("Region\nNorth\n", encoding="utf-8")

        def accept_unchanged(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.assertEqual(dialog._preview_candidate.rows[0]["Region"], "North")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_unchanged):
            self.assertTrue(controller.transform_data_dialog())

        self.assertEqual(controller._rows, [{"Region": "North"}])
        self.assertEqual(controller._raw_candidates[source_id].rows, [{"Region": "North"}])

    def test_power_query_apply_refreshes_active_and_inactive_local_sources_atomically(self) -> None:
        details_path = self.root / "details.csv"
        sales_path = self.root / "sales.csv"
        details_path.write_text("Label\noriginal\n", encoding="utf-8")
        sales_path.write_text("Region\nEast\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(details_path, parse_file(details_path)))
        details_id = controller._active_source_id
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = controller._active_source_id
        details_path.write_text("Label\n  updated  \n", encoding="utf-8")
        sales_path.write_text("Region\nNorth\n", encoding="utf-8")

        def accept_independent_edit(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[details_id])
            self.assertEqual(dialog._preview_candidate.rows[0]["Label"], "  updated  ")
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Label")
            dialog._add_step()
            dialog.query_list.setCurrentRow(rows_by_id[sales_id])
            self.assertEqual(dialog._preview_candidate.rows[0]["Region"], "North")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_independent_edit):
            self.assertTrue(controller.transform_data_dialog())

        self.assertEqual(controller._rows, [{"Region": "North"}])
        self.assertEqual(controller._loaded_candidates[details_id].rows, [{"Label": "updated"}])
        self.assertEqual(controller._raw_candidates[details_id].rows, [{"Label": "  updated  "}])

    def test_power_query_dependent_preview_uses_refreshed_local_inputs(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Region\n East \n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        sales_id = controller._active_source_id
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nWest", name="Archive")
        ))
        archive_id = controller._active_source_id
        first = controller._loaded_candidates[sales_id]
        second = controller._loaded_candidates[archive_id]
        combined = type(first)(
            "query",
            first.headers,
            [*first.rows, *second.rows],
            {},
            [],
        )
        self.assertTrue(controller._create_saved_query(
            "Combined",
            [sales_id, archive_id],
            combined,
            {"operation": "append", "source_ids": [sales_id, archive_id]},
            {"Region": "text"},
        ))
        combined_id = controller._active_source_id
        source_path.write_text("Region\n North \n", encoding="utf-8")

        def accept_dependent_trim(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[combined_id])
            self.assertEqual(
                [row["Region"] for row in dialog._preview_candidate.rows],
                [" North ", "West"],
            )
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_dependent_trim):
            self.assertTrue(controller.transform_data_dialog())

        self.assertEqual(controller._active_source_id, combined_id)
        self.assertEqual(controller._rows, [{"Region": "North"}, {"Region": "West"}])
        self.assertEqual(controller._loaded_candidates[combined_id].rows, controller._rows)

    def test_power_query_reference_query_is_atomic_typed_and_tracks_source_refresh(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Region,Revenue\nEast,1.25\nWest,2.5\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        source_id = controller._active_source_id
        before_cancel = copy.deepcopy(controller._project)

        def cancel_reference(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog._create_reference_query()
            self.assertEqual(dialog._query_order[-1], dialog._active_query_id)
            dialog.reject()
            return QDialog.DialogCode.Rejected

        with patch.object(TransformDataDialog, "exec", new=cancel_reference):
            self.assertFalse(controller.transform_data_dialog())
        self.assertEqual(controller._project, before_cancel)

        created: dict[str, str] = {}

        def accept_reference(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("convert_type")
            )
            dialog.column_combo.setCurrentText("Revenue")
            dialog.option_combo.setCurrentIndex(
                dialog.option_combo.findData("decimal_number")
            )
            dialog._add_step()
            home_index = dialog.ribbon_tabs.indexOf(
                next(
                    dialog.ribbon_tabs.widget(index)
                    for index in range(dialog.ribbon_tabs.count())
                    if dialog.ribbon_tabs.tabText(index) == "Home"
                )
            )
            dialog.ribbon_tabs.setCurrentIndex(home_index)
            manage_button = dialog.findChild(QToolButton, "powerQueryManageQueriesButton")
            self.assertIsNotNone(manage_button)
            reference_action = next(
                action for action in manage_button.menu().actions()
                if action.text() == "Reference Query"
            )
            reference_action.trigger()
            reference_id = dialog._active_query_id
            reference = dialog._query_states[reference_id]
            self.assertEqual(reference["query_definition"], {
                "operation": "reference", "source_ids": [source_id],
            })
            self.assertEqual(reference["source_column_types"]["Revenue"], "decimal_number")
            dialog._refresh_column_profiles()
            self.assertEqual(dialog.profile_table.item(1, 1).text(), "decimal_number")
            created["id"] = reference_id
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_reference):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)

        reference_id = created["id"]
        reference_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == reference_id
        )
        self.assertEqual(reference_source["query_definition"], {
            "operation": "reference", "source_ids": [source_id],
        })
        reference_table = next(
            item for item in controller._project["model"]["tables"]
            if item.get("source_id") == reference_id
        )
        self.assertEqual(reference_table["column_types"]["Revenue"], "decimal_number")
        self.assertEqual(controller._active_source_id, reference_id)
        self.assertEqual(controller._loaded_candidates[reference_id].rows, [
            {"Region": "East", "Revenue": Decimal("1.25")},
            {"Region": "West", "Revenue": Decimal("2.5")},
        ])

        project_path = self.root / "referenced.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._loaded_candidates[reference_id],
                         controller._loaded_candidates[reference_id])

        source_path.write_text("Region,Revenue\nNorth,7.75\nSouth,8.25\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened._loaded_candidates[reference_id].rows, [
            {"Region": "North", "Revenue": Decimal("7.75")},
            {"Region": "South", "Revenue": Decimal("8.25")},
        ])
        refreshed_table = next(
            item for item in reopened._project["model"]["tables"]
            if item.get("source_id") == reference_id
        )
        self.assertEqual(refreshed_table["column_types"]["Revenue"], "decimal_number")

    def test_power_query_reference_tracks_parent_edits_made_after_creation(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text(
            "Region,Revenue\nEast,1.25\nWest,2.5\n", encoding="utf-8"
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        source_id = controller._active_source_id
        created: dict[str, str] = {}

        def edit_parent_after_reference(
            dialog: TransformDataDialog,
        ) -> QDialog.DialogCode:
            home_index = next(
                index for index in range(dialog.ribbon_tabs.count())
                if dialog.ribbon_tabs.tabText(index) == "Home"
            )
            dialog.ribbon_tabs.setCurrentIndex(home_index)
            manage_button = dialog.findChild(QToolButton, "powerQueryManageQueriesButton")
            self.assertIsNotNone(manage_button)
            reference_action = next(
                action for action in manage_button.menu().actions()
                if action.text() == "Reference Query"
            )
            reference_action.trigger()
            reference_id = dialog._active_query_id
            created["id"] = reference_id

            parent_row = dialog._query_order.index(source_id)
            dialog._switch_query(parent_row)
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("convert_type")
            )
            dialog.column_combo.setCurrentText("Revenue")
            dialog.option_combo.setCurrentIndex(
                dialog.option_combo.findData("decimal_number")
            )
            dialog._add_step()
            dialog.operation_combo.setCurrentIndex(
                dialog.operation_combo.findData("rename_column")
            )
            dialog.column_combo.setCurrentText("Region")
            dialog.value_edit.setText("Market")
            dialog._add_step()

            reference_row = dialog._query_order.index(reference_id)
            dialog._switch_query(reference_row)
            reference = dialog._query_states[reference_id]
            self.assertEqual(reference["source_candidate"].headers, ["Market", "Revenue"])
            self.assertEqual(reference["source_column_types"]["Revenue"], "decimal_number")
            dialog.query_refresh_included_checkbox.setChecked(False)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=edit_parent_after_reference):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)

        reference_id = created["id"]
        self.assertEqual(controller._loaded_candidates[reference_id].headers, ["Market", "Revenue"])
        self.assertEqual(controller._loaded_candidates[reference_id].rows, [
            {"Market": "East", "Revenue": Decimal("1.25")},
            {"Market": "West", "Revenue": Decimal("2.5")},
        ])
        reference_table = next(
            item for item in controller._project["model"]["tables"]
            if item.get("source_id") == reference_id
        )
        self.assertEqual(reference_table["column_types"]["Revenue"], "decimal_number")
        reference_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == reference_id
        )
        self.assertFalse(reference_source.get("include_in_report_refresh", True))

        source_path.write_text(
            "Region,Revenue\nNorth,7.75\nSouth,8.25\n", encoding="utf-8"
        )
        controller.refresh_all_sources()
        self.assertEqual(controller._loaded_candidates[source_id].rows, [
            {"Market": "North", "Revenue": Decimal("7.75")},
            {"Market": "South", "Revenue": Decimal("8.25")},
        ])
        self.assertEqual(controller._loaded_candidates[reference_id].rows, [
            {"Market": "East", "Revenue": Decimal("1.25")},
            {"Market": "West", "Revenue": Decimal("2.5")},
        ])

    def test_reference_name_skips_names_reserved_by_unloaded_tables(self) -> None:
        candidate = parse_pasted_table("Revenue\n10", name="Sales")
        dialog = TransformDataDialog(
            candidate,
            query_name="Sales",
            reserved_query_names={"Sales (Reference)"},
        )

        dialog._create_reference_query()

        self.assertEqual(
            dialog._query_states[dialog._active_query_id]["name"],
            "Sales (Reference 2)",
        )

    def test_power_query_apply_rejects_reference_name_collision_atomically(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Revenue\n10\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        source_id = controller._active_source_id
        project_before = copy.deepcopy(controller._project)

        self.assertFalse(controller._commit_transform_session({
            "new-reference-id": {
                "is_new_query": True,
                "name": "Sales",
                "query_definition": {
                    "operation": "reference",
                    "source_ids": [source_id],
                },
            },
        }))

        self.assertEqual(controller._project, project_before)
        self.assertIn("already exists", controller.statusMessage)

    def test_power_query_duplicates_root_and_saved_queries_through_refresh(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Region,Revenue\n East ,10\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        sales_id = str(controller._active_source_id)
        steps = [{"op": "trim_text", "column": "Region"}]
        raw = controller._raw_candidates[sales_id]
        self.assertTrue(controller._commit_transform_steps(
            sales_id,
            steps,
            apply_transformations(raw, steps),
            previewed_source=raw,
        ))
        sales = controller._loaded_candidates[sales_id]
        self.assertTrue(controller._create_saved_query(
            "Sales Reference",
            [sales_id],
            sales,
            {"operation": "reference", "source_ids": [sales_id]},
            {"Region": "text", "Revenue": "text"},
        ))
        reference_id = str(controller._active_source_id)
        created_ids: dict[str, str] = {}

        def duplicate_both(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[reference_id])
            dialog._duplicate_selected_query()
            created_ids["reference"] = dialog._active_query_id
            dialog.query_list.setCurrentRow(rows_by_id[sales_id])
            dialog._duplicate_selected_query()
            created_ids["root"] = dialog._active_query_id
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=duplicate_both):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)

        reference_copy = created_ids["reference"]
        sales_copy = created_ids["root"]
        self.assertEqual(controller._loaded_candidates[reference_copy].rows, sales.rows)
        self.assertEqual(controller._loaded_candidates[sales_copy].rows, sales.rows)
        for duplicate_id in (reference_copy, sales_copy):
            source = next(
                item for item in controller._project["data_sources"]
                if item["id"] == duplicate_id
            )
            table = next(
                item for item in controller._project["model"]["tables"]
                if item.get("source_id") == duplicate_id
            )
            self.assertEqual(
                source["transform_steps"],
                steps if duplicate_id == sales_copy else [],
            )
            self.assertNotEqual(table["id"], sales_id)

        project_path = self.root / "duplicated-queries.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        source_path.write_text("Region,Revenue\n North ,25\n", encoding="utf-8")
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[sales_id].rows, [
            {"Region": "North", "Revenue": "25"},
        ])
        self.assertEqual(reopened._loaded_candidates[sales_copy].rows, [
            {"Region": "North", "Revenue": "25"},
        ])
        self.assertEqual(reopened._loaded_candidates[reference_copy].rows, [
            {"Region": "North", "Revenue": "25"},
        ])

    def test_power_query_delete_is_atomic_and_preserves_linked_file(self) -> None:
        sales_path = self.root / "sales.csv"
        sales_path.write_text("Revenue\n10\n", encoding="utf-8")
        archive_path = self.root / "archive.csv"
        archive_path.write_text("Revenue\n5\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = str(controller._active_source_id)
        self.assertTrue(controller._commit_import(archive_path, parse_file(archive_path)))
        archive_id = str(controller._active_source_id)
        sales_before = controller._loaded_candidates[sales_id]

        def delete_active(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[archive_id])
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                dialog._delete_selected_query()
            self.assertNotIn(archive_id, dialog._query_states)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=delete_active):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)

        self.assertTrue(archive_path.exists())
        self.assertNotIn(archive_id, {item["id"] for item in controller._project["data_sources"]})
        self.assertNotIn(archive_id, {item.get("source_id") for item in controller._project["model"]["tables"]})
        self.assertNotIn(archive_id, controller._loaded_candidates)
        self.assertNotIn(archive_id, controller._raw_candidates)
        self.assertEqual(controller._loaded_candidates[sales_id], sales_before)
        self.assertEqual(controller._active_source_id, sales_id)
        self.assertIn("Deleted 1 query", controller.statusMessage)

        project_path = self.root / "deleted-query.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            {str(item["id"]) for item in reopened._project["data_sources"]},
            {sales_id},
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[sales_id].rows, [{"Revenue": "10"}])

    def test_power_query_failed_queries_remain_deletable_with_their_parent(self) -> None:
        sales_path = self.root / "sales.csv"
        sales_path.write_text("Revenue\n10\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = str(controller._active_source_id)
        sales_candidate = controller._loaded_candidates[sales_id]
        reference_candidate = type(sales_candidate)(
            "query", list(sales_candidate.headers), list(sales_candidate.rows), {}, []
        )
        self.assertTrue(controller._create_saved_query(
            "Sales Reference",
            [sales_id],
            reference_candidate,
            {"operation": "reference", "source_ids": [sales_id]},
            {"Revenue": "text"},
        ))
        reference_id = str(controller._active_source_id)
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Units\n2", name="Archive")
        ))
        archive_id = str(controller._active_source_id)
        project_path = self.root / "missing-query-source.npa"
        self.assertTrue(controller._save_to(project_path))

        sales_path.unlink()
        reopened = self.controller()
        with patch.object(QMessageBox, "warning"):
            self.assertTrue(reopened.open_project_path(project_path))
        self.assertIn(archive_id, reopened._loaded_candidates)
        self.assertNotIn(sales_id, reopened._loaded_candidates)
        self.assertNotIn(reference_id, reopened._loaded_candidates)

        def delete_failed_queries(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.assertTrue(dialog._query_states[sales_id]["is_unavailable"])
            self.assertTrue(dialog._query_states[reference_id]["is_unavailable"])
            dialog.query_list.setCurrentRow(dialog._query_order.index(reference_id))
            self.assertFalse(dialog.ribbon_tabs.isEnabled())
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                dialog._delete_selected_query()
            dialog.query_list.setCurrentRow(dialog._query_order.index(sales_id))
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                dialog._delete_selected_query()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=delete_failed_queries):
            self.assertTrue(reopened.transform_data_dialog(), reopened._status_message)

        remaining_ids = {
            str(item.get("id", "")) for item in reopened._project["data_sources"]
        }
        self.assertEqual(remaining_ids, {archive_id})
        self.assertTrue(sales_path.parent.exists())
        self.assertFalse(sales_path.exists())
        self.assertNotIn(sales_id, reopened._source_load_errors)
        self.assertNotIn(reference_id, reopened._source_load_errors)

    def test_power_query_reuses_name_freed_by_deletion_in_same_apply(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Revenue\n10", name="Sales")
        ))
        sales_id = str(controller._active_source_id)
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Units\n2", name="Archive")
        ))
        archive_id = str(controller._active_source_id)
        created: dict[str, str] = {}

        def replace_name_in_one_apply(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(sales_id))
            with patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
            ):
                dialog._delete_selected_query()
            dialog.query_list.setCurrentRow(dialog._query_order.index(archive_id))
            dialog._create_reference_query()
            created["id"] = dialog._active_query_id
            dialog.query_name_edit.setText("Sales")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=replace_name_in_one_apply):
            self.assertTrue(controller.transform_data_dialog(), controller._status_message)

        new_id = created["id"]
        tables = controller._project["model"]["tables"]
        sources = controller._project["data_sources"]
        self.assertNotIn(sales_id, {str(item.get("source_id") or item.get("id")) for item in tables})
        new_table = next(
            item for item in tables
            if str(item.get("source_id") or item.get("id")) == new_id
        )
        self.assertEqual(new_table["name"], "Sales")
        new_source = next(item for item in sources if str(item.get("id")) == new_id)
        self.assertEqual(new_source["query_definition"], {
            "operation": "reference", "source_ids": [archive_id],
        })

    def test_power_query_delete_blocks_query_relationship_report_and_dax_dependencies(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("RegionID,Revenue\n1,10", name="Sales")
        ))
        sales_id = str(controller._active_source_id)
        sales_name = controller._active_model_table_name()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("RegionID,Units\n1,2", name="Archive")
        ))
        archive_id = str(controller._active_source_id)
        archive_table = next(
            item for item in controller._project["model"]["tables"]
            if item.get("source_id") == archive_id
        )
        archive_table["calculated_columns"] = [{
            "name": "Linked Region",
            "expression": "'Sales'[RegionID]",
        }]
        archive_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == archive_id
        )
        archive_raw = controller._raw_candidates[archive_id]
        archive_steps = []
        controller._project["model"]["relationships"].append({
            "relationship_version": 1,
            "id": "sales-archive-region",
            "from": f"{sales_name}[RegionID]",
            "to": "Archive[RegionID]",
            "from_table_id": sales_id,
            "from_column": "RegionID",
            "to_table_id": archive_id,
            "to_column": "RegionID",
            "cardinality": "one_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        })
        controller._project["report"]["filters"].append({
            "table_id": sales_id,
            "column": "Revenue",
            "clauses": [{"operator": "equals", "value": "10"}],
            "logic": "and",
        })
        controller._project["model"]["measures"].append({
            "name": "Gross Revenue",
            "expression": f"SUM('{sales_name}'[Revenue])",
        })
        project_before = copy.deepcopy(controller._project)
        loaded_before = copy.deepcopy(controller._loaded_candidates)
        raw_before = copy.deepcopy(controller._raw_candidates)

        self.assertFalse(controller._commit_transform_session({
            archive_id: {
                "name": str(archive_source.get("query_name", archive_source["name"])),
                "source_candidate": archive_raw,
                "candidate": apply_transformations(archive_raw, archive_steps),
                "steps": archive_steps,
            },
        }, deleted_query_ids={sales_id}))

        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._loaded_candidates, loaded_before)
        self.assertEqual(controller._raw_candidates, raw_before)
        self.assertIn("relationship", controller.statusMessage)
        self.assertIn("report filter", controller.statusMessage)
        self.assertIn("Gross Revenue", controller.statusMessage)
        self.assertIn("calculated column", controller.statusMessage)

    def test_power_query_rebuilds_unchanged_dependent_after_upstream_step_edit(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Region\nEast\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        sales_id = controller._active_source_id
        sales = controller._loaded_candidates[sales_id]
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nWest", name="Archive")
        ))
        archive_id = controller._active_source_id
        combined = type(sales)(
            "query",
            sales.headers,
            [*sales.rows, *controller._loaded_candidates[archive_id].rows],
            {},
            [],
        )
        self.assertTrue(controller._create_saved_query(
            "Filtered Sales",
            [sales_id, archive_id],
            combined,
            {"operation": "append", "source_ids": [sales_id, archive_id]},
            {"Region": "text"},
        ))
        query_id = controller._active_source_id
        source_path.write_text("Region\n North \n", encoding="utf-8")

        def accept_upstream_edit(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[sales_id])
            self.assertEqual(dialog._preview_candidate.rows, [{"Region": " North "}])
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog.query_list.setCurrentRow(rows_by_id[query_id])
            self.assertEqual(
                dialog._preview_candidate.rows,
                [{"Region": " North "}, {"Region": "West"}],
            )
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_upstream_edit):
            self.assertTrue(controller.transform_data_dialog())

        self.assertEqual(controller._loaded_candidates[sales_id].rows, [{"Region": "North"}])
        self.assertEqual(
            controller._loaded_candidates[query_id].rows,
            [{"Region": "North"}, {"Region": "West"}],
        )

    def test_power_query_rejected_settings_do_not_update_raw_source_snapshots(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Region,Keep\nEast,1\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        source_id = controller._active_source_id
        steps = [{"op": "keep_columns", "columns": ["Keep"]}]
        initial_raw = controller._raw_candidates[source_id]
        self.assertTrue(controller._commit_transform_steps(
            source_id,
            steps,
            apply_transformations(initial_raw, steps),
            previewed_source=initial_raw,
        ))
        saved_raw = controller._raw_candidates[source_id]

        source_path.write_text("Region,Keep\nNorth,1\n", encoding="utf-8")
        refreshed = parse_file(source_path)
        self.assertNotEqual(refreshed, saved_raw)
        unchanged_output = apply_transformations(refreshed, steps)
        self.assertFalse(controller._commit_transform_session({
            source_id: {
                "steps": steps,
                "source_candidate": refreshed,
                "candidate": unchanged_output,
                "query_group": "G" * 81,
            }
        }))

        self.assertEqual(controller._raw_candidates[source_id], saved_raw)
        self.assertEqual(controller._loaded_candidates[source_id].rows, [{"Keep": "1"}])

    def test_power_query_preserves_excluded_query_when_upstream_file_changes(self) -> None:
        source_path = self.root / "sales.csv"
        source_path.write_text("Region\nEast\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        sales_id = controller._active_source_id
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nWest", name="Archive")
        ))
        archive_id = controller._active_source_id
        source_candidate = controller._loaded_candidates[sales_id]
        combined_raw = type(source_candidate)(
            "query",
            source_candidate.headers,
            [*source_candidate.rows, *controller._loaded_candidates[archive_id].rows],
            {},
            [],
        )
        self.assertTrue(controller._create_saved_query(
            "Combined",
            [sales_id, archive_id],
            combined_raw,
            {"operation": "append", "source_ids": [sales_id, archive_id]},
            {"Region": "text"},
        ))
        combined_id = controller._active_source_id
        self.assertTrue(controller.setQueryRefreshIncluded(combined_id, False))
        saved_combined = copy.deepcopy(controller._loaded_candidates[combined_id])
        saved_combined_raw = copy.deepcopy(controller._raw_candidates[combined_id])
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Label\n  note  ", name="Notes")
        ))
        notes_id = controller._active_source_id
        source_path.write_text("Region\nNorth\n", encoding="utf-8")

        def accept_unrelated_edit(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[combined_id])
            self.assertEqual(
                [row["Region"] for row in dialog._preview_candidate.rows],
                ["East", "West"],
            )
            dialog.query_list.setCurrentRow(rows_by_id[notes_id])
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Label")
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_unrelated_edit):
            self.assertTrue(controller.transform_data_dialog())

        self.assertEqual(controller._loaded_candidates[sales_id].rows, [{"Region": "North"}])
        self.assertEqual(controller._loaded_candidates[combined_id], saved_combined)
        self.assertEqual(controller._raw_candidates[combined_id], saved_combined_raw)
        self.assertEqual(controller._loaded_candidates[notes_id].rows, [{"Label": "note"}])

    def test_power_query_settings_assigns_and_persists_query_group(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nEast", name="Sales")
        ))
        source_id = controller._active_source_id

        def assign_group(dialog: TransformDataDialog) -> QDialog.DialogCode:
            self.assertEqual(dialog.query_group_edit.text(), "")
            dialog.query_group_edit.setText("Operations")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=assign_group):
            self.assertTrue(controller.transform_data_dialog())

        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(source["query_group"], "Operations")
        self.assertEqual(controller._loaded_candidates[source_id].rows, [{"Region": "East"}])

        path = self.root / "grouped.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(reopened_source["query_group"], "Operations")

    def test_power_query_settings_edits_saved_query_load_and_refresh_flags(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nEast", name="Sales")
        ))
        sales_id = controller._active_source_id
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nWest", name="Archive")
        ))
        archive_id = controller._active_source_id
        query_candidate = type(controller._loaded_candidates[sales_id])(
            "query",
            ["Region"],
            [{"Region": "East"}, {"Region": "West"}],
            {},
            [],
        )
        self.assertTrue(controller._create_saved_query(
            "Combined",
            [sales_id, archive_id],
            query_candidate,
            {"operation": "append", "source_ids": [sales_id, archive_id]},
            {"Region": "text"},
        ))
        query_id = controller._active_source_id

        def exclude_query(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[query_id])
            self.assertFalse(dialog.query_load_enabled_checkbox.isHidden())
            self.assertTrue(dialog.query_load_enabled_checkbox.isChecked())
            self.assertTrue(dialog.query_refresh_included_checkbox.isChecked())
            dialog.query_load_enabled_checkbox.setChecked(False)
            dialog.query_refresh_included_checkbox.setChecked(False)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=exclude_query):
            self.assertTrue(controller.transform_data_dialog())

        saved_query = next(
            item for item in controller._project["data_sources"]
            if item["id"] == query_id
        )
        self.assertFalse(saved_query["load_enabled"])
        self.assertFalse(saved_query["include_in_report_refresh"])
        self.assertIn(controller._active_source_id, {sales_id, archive_id})
        model_entry = next(
            item for item in controller._table_catalog
            if item["sourceId"] == query_id
        )
        self.assertFalse(model_entry["loaded"])

        path = self.root / "query-settings.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        reopened_query = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == query_id
        )
        self.assertFalse(reopened_query["load_enabled"])
        self.assertFalse(reopened_query["include_in_report_refresh"])

        def include_query(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[query_id])
            self.assertFalse(dialog._query_states[query_id]["load_enabled"])
            self.assertFalse(dialog.query_load_enabled_checkbox.isChecked())
            self.assertFalse(dialog.query_refresh_included_checkbox.isChecked())
            dialog.query_load_enabled_checkbox.setChecked(True)
            dialog.query_refresh_included_checkbox.setChecked(True)
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=include_query):
            self.assertTrue(reopened.transform_data_dialog())

        included_query = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == query_id
        )
        self.assertTrue(included_query["load_enabled"])
        self.assertTrue(included_query["include_in_report_refresh"])
        model_entry = next(
            item for item in reopened._table_catalog
            if item["sourceId"] == query_id
        )
        self.assertTrue(model_entry["loaded"])

    def test_power_query_applied_step_name_and_description_persist(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Customer\n  Ada  ", name="Sales")
        ))
        source_id = controller._active_source_id
        source_record = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        raw = controller._session_raw_candidate_for_source(source_record)
        steps = [{"op": "trim_text", "column": "Customer"}]
        self.assertTrue(controller._commit_transform_session({
            source_id: {
                "steps": steps,
                "source_candidate": raw,
                "candidate": apply_transformations(raw, steps),
                "step_metadata": [{
                    "name": "Clean customer",
                    "description": "Remove surrounding whitespace before modeling.",
                }],
            }
        }), controller._status_message)

        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(source["step_metadata"], [{
            "name": "Clean customer",
            "description": "Remove surrounding whitespace before modeling.",
        }])
        path = self.root / "step-metadata.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        reopened_source = next(
            item for item in reopened._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(reopened_source["step_metadata"], source["step_metadata"])
        self.assertEqual(reopened._loaded_candidates[source_id].rows, [{"Customer": "Ada"}])

    def test_power_query_renames_model_table_and_preserves_dax_references(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Revenue\n10", name="Sales")
        ))
        source_id = controller._active_source_id
        self.assertTrue(controller.create_measure("Gross Revenue", "SUM('Sales'[Revenue])"))
        sales_candidate = controller._loaded_candidates[source_id]
        distinct_candidate = type(sales_candidate)(
            "query", ["Revenue"], [{"Revenue": "10"}], {}, []
        )
        self.assertTrue(controller._create_saved_query(
            "Distinct Revenue",
            [source_id],
            distinct_candidate,
            {
                "operation": "calculated_table",
                "source_ids": [source_id],
                "expression": "DISTINCT('Sales'[Revenue])",
                "source_table": "Sales",
            },
            {"Revenue": "text"},
        ))
        calculated_table_id = controller._active_source_id

        def rename_query(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[source_id])
            self.assertEqual(dialog.query_name_edit.text(), "Sales")
            dialog.query_name_edit.setText("Regional Sales")
            dialog.query_description_edit.setPlainText("Revenue grouped by sales region.")
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=rename_query):
            self.assertTrue(controller.transform_data_dialog())

        table = next(
            item for item in controller._project["model"]["tables"]
            if item.get("source_id") == source_id
        )
        source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == source_id
        )
        self.assertEqual(table["name"], "Regional Sales")
        self.assertEqual(source["query_name"], "Regional Sales")
        self.assertEqual(source["description"], "Revenue grouped by sales region.")
        self.assertEqual(
            controller._project["model"]["measures"][0]["expression"],
            "SUM('Regional Sales'[Revenue])",
        )
        calculated_source = next(
            item for item in controller._project["data_sources"]
            if item["id"] == calculated_table_id
        )
        self.assertEqual(
            calculated_source["query_definition"]["source_table"], "Regional Sales"
        )
        self.assertEqual(
            calculated_source["query_definition"]["expression"],
            "DISTINCT('Regional Sales'[Revenue])",
        )
        self.assertEqual(controller._measure_values["Gross Revenue"], "10")

        path = self.root / "renamed-query.npa"
        self.assertTrue(controller._save_to(path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(path))
        self.assertEqual(reopened._project["model"]["measures"][0]["expression"],
                         "SUM('Regional Sales'[Revenue])")
        self.assertEqual(reopened._measure_values["Gross Revenue"], "10")
        self.assertEqual(reopened._loaded_candidates[calculated_table_id].rows,
                         [{"Revenue": "10"}])

    def test_single_query_apply_updates_the_raw_snapshot_after_source_change(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Region\nEast\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        source_id = controller._active_source_id
        source.write_text("Region\nNorth\n", encoding="utf-8")
        fresh = parse_file(source)

        self.assertTrue(controller._commit_transform_steps(
            source_id,
            [],
            apply_transformations(fresh, []),
            previewed_source=fresh,
        ))

        self.assertEqual(controller._raw_candidates[source_id].source_id, source_id)
        self.assertEqual(controller._raw_candidates[source_id].rows, fresh.rows)
        self.assertEqual(controller._rows, [{"Region": "North"}])

    def test_power_query_session_rejects_staged_upstream_and_dependent_edits_atomically(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\n East ", name="Sales")
        ))
        sales_id = controller._active_source_id
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Region\nWest", name="Archive")
        ))
        archive_id = controller._active_source_id
        combined = controller._loaded_candidates[sales_id]
        combined = type(combined)(
            "query",
            combined.headers,
            [*combined.rows, *controller._loaded_candidates[archive_id].rows],
            {},
            [],
        )
        self.assertTrue(controller._create_saved_query(
            "Combined",
            [sales_id, archive_id],
            combined,
            {"operation": "append", "source_ids": [sales_id, archive_id]},
            {"Region": "text"},
        ))
        combined_id = controller._active_source_id
        project_before = copy.deepcopy(controller._project)
        rows_before = copy.deepcopy(controller._rows)

        def accept_dependent_edits(dialog: TransformDataDialog) -> QDialog.DialogCode:
            rows_by_id = {
                str(dialog.query_list.item(index).data(Qt.ItemDataRole.UserRole)): index
                for index in range(dialog.query_list.count())
            }
            dialog.query_list.setCurrentRow(rows_by_id[sales_id])
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog.query_list.setCurrentRow(rows_by_id[combined_id])
            dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
            dialog.column_combo.setCurrentText("Region")
            dialog._add_step()
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept_dependent_edits):
            self.assertFalse(controller.transform_data_dialog())

        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._rows, rows_before)
        self.assertIn("one at a time", controller.statusMessage)

    def test_transform_steps_persist_replay_on_open_and_refresh(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Region,Revenue\nEast,12\nWest,20\n", encoding="utf-8")
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        steps = [
            {"op": "convert_type", "column": "Revenue", "type": "number"},
            {"op": "filter_rows", "column": "Revenue", "operator": "greater_than", "value": "10"},
            {"op": "sort_rows", "column": "Revenue", "direction": "desc"},
        ]
        transformed = apply_transformations(raw, steps)
        source_id = controller._active_source_id
        self.assertTrue(controller._commit_transform_steps(source_id, steps, transformed))
        self.assertEqual([row["Revenue"] for row in controller._rows], [Decimal("20"), Decimal("12")])

        project_path = self.root / "report.npa"
        self.assertTrue(controller._save_to(project_path))
        source.write_text(
            "Region,Revenue\nEast,12\nWest,20\nNorth,30\nSouth,5\n", encoding="utf-8"
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Revenue"] for row in reopened._rows], [Decimal("30"), Decimal("20"), Decimal("12")])
        reopened.refresh_source()
        self.assertEqual([row["Revenue"] for row in reopened._rows], [Decimal("30"), Decimal("20"), Decimal("12")])

    def test_applied_step_settings_save_reopen_and_replay_on_source_refresh(self) -> None:
        source = self.root / "settings.csv"
        source.write_text("Region\nEast\nWest\n", encoding="utf-8")
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        source_id = str(controller._active_source_id)
        initial_steps = [{
            "op": "filter_rows",
            "column": "Region",
            "operator": "equals",
            "value": "East",
        }]
        self.assertTrue(controller._commit_transform_steps(
            source_id,
            initial_steps,
            apply_transformations(raw, initial_steps),
            previewed_source=raw,
        ))

        def edit_filter_settings(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.step_list.setCurrentRow(0)

            def save_settings(settings: QDialog) -> QDialog.DialogCode:
                self.assertEqual(dialog.value_edit.text(), "East")
                dialog.value_edit.setText("West")
                buttons = settings.findChild(
                    QDialogButtonBox, "powerQueryStepSettingsButtons"
                )
                self.assertIsNotNone(buttons)
                buttons.button(QDialogButtonBox.StandardButton.Save).click()
                return settings.result()

            with patch.object(QDialog, "exec", new=save_settings):
                dialog._edit_selected_step_settings()
            self.assertEqual(dialog._steps[0]["value"], "West")
            self.assertEqual(dialog._preview_candidate.rows, [{"Region": "West"}])
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=edit_filter_settings):
            self.assertTrue(controller.transform_data_dialog(), controller.statusMessage)
        saved_step = controller._project["data_sources"][0]["transform_steps"][0]
        self.assertEqual(saved_step["value"], "West")
        self.assertEqual(controller._rows, [{"Region": "West"}])

        project_path = self.root / "step-settings.npa"
        self.assertTrue(controller._save_to(project_path))
        source.write_text(
            "Region\nWest\nNorth\nEast\n", encoding="utf-8"
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{"Region": "West"}])
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"Region": "West"}])

    def test_extended_transform_steps_save_reopen_and_replay_after_refresh(self) -> None:
        source = self.root / "sales.csv"
        source.write_text(
            "Name,Region,Sales\nAlice, East ,10\nBob,East,20\nBob,East,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        steps = [
            {"op": "trim_text", "column": "Region"},
            {"op": "replace_value", "column": "Region", "value": "East", "replacement": "Eastern"},
            {"op": "remove_duplicates"},
            {"op": "keep_columns", "columns": ["Region", "Sales"]},
            {"op": "sort_rows", "column": "Sales", "direction": "desc"},
        ]
        transformed = apply_transformations(raw, steps)
        self.assertTrue(controller._commit_transform_steps(
            controller._active_source_id, steps, transformed
        ))
        self.assertEqual(controller._headers, ["Region", "Sales"])
        self.assertEqual(controller._rows, [
            {"Region": "Eastern", "Sales": "20"},
            {"Region": "Eastern", "Sales": "10"},
        ])

        project = self.root / "extended-transform.npa"
        self.assertTrue(controller._save_to(project))
        source.write_text(
            "Name,Region,Sales\nAlice, East ,10\nBob,East,20\nBob,East,20\nCara,West,30\n",
            encoding="utf-8",
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project))
        self.assertEqual(reopened._headers, ["Region", "Sales"])
        self.assertEqual(reopened._rows[0], {"Region": "West", "Sales": "30"})
        reopened.refresh_source()
        self.assertEqual(reopened.rowCount, 3)

    def test_conversion_error_survives_source_refresh_as_a_cell_error(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Revenue\n12\n", encoding="utf-8")
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        steps = [{"op": "convert_type", "column": "Revenue", "type": "number"}]
        self.assertTrue(controller._commit_transform_steps(
            controller._active_source_id, steps, apply_transformations(raw, steps)
        ))
        source.write_text("Revenue\nnot-a-number\n", encoding="utf-8")

        controller.refresh_source()

        # Refresh succeeds: the conversion failure is a cell error in the query
        # result and loads into the model as a blank.
        self.assertEqual(len(controller._rows), 1)
        self.assertIsNone(controller._rows[0]["Revenue"])
        error = controller._query_candidates[controller._active_source_id].rows[0]["Revenue"]
        self.assertIsInstance(error, PowerQueryCellError)
        self.assertEqual((error.value, error.target_type, error.row), (
            "not-a-number", "decimal_number", 1,
        ))
        self.assertNotIn("Could not refresh", controller.sourceWarning)

    def test_typed_values_and_remove_errors_survive_apply_reopen_and_refresh(self) -> None:
        source = self.root / "typed-values.json"
        source.write_text(
            '[{"Value":0,"Note":"ok"},{"Value":null,"Note":null},'
            '{"Value":"","Note":""},{"Value":"bad","Note":"bad"}]',
            encoding="utf-8",
        )
        controller = self.controller()
        raw = parse_file(source)
        self.assertTrue(controller._commit_import(source, raw))
        source_id = controller._active_source_id
        self.assertIsNotNone(source_id)
        raw_profile = controller.profileColumn("Value")
        self.assertEqual(
            (raw_profile["nullCount"], raw_profile["emptyCount"], raw_profile["errorCount"]),
            (1, 1, 0),
        )

        convert_step = {
            "op": "convert_type", "column": "Value", "type": "whole_number",
        }
        converted = apply_transformations(raw, [convert_step])
        self.assertTrue(controller._commit_transform_steps(
            source_id, [convert_step], converted, previewed_source=raw,
        ))
        # The query result keeps the typed errors; the loaded model has blanks
        # at the DataFormat.Error cells, as Power BI Desktop's model does.
        error = controller._query_candidates[source_id].rows[3]["Value"]
        self.assertIsInstance(error, PowerQueryCellError)
        self.assertEqual((error.reason, error.value, error.target_type, error.row), (
            "DataFormat.Error", "bad", "whole_number", 4,
        ))
        current = controller._loaded_candidates[source_id]
        self.assertIsNone(current.rows[3]["Value"])
        self.assertEqual(
            [row["Value"] for row in current.rows[:3]], [0, None, None],
        )
        profile = controller.profileColumn("Value")
        self.assertEqual(
            (profile["nullCount"], profile["emptyCount"], profile["errorCount"]),
            (3, 0, 0),
        )
        self.assertEqual(
            (controller.profileColumn("Note")["nullCount"],
             controller.profileColumn("Note")["emptyCount"]),
            (1, 1),
        )

        steps = [convert_step, {"op": "remove_rows_with_errors"}]
        cleaned = apply_transformations(raw, steps)
        self.assertTrue(controller._commit_transform_steps(
            source_id, steps, cleaned, previewed_source=raw,
        ))
        expected = [0, None]
        self.assertEqual(
            [row["Value"] for row in controller._loaded_candidates[source_id].rows],
            expected,
        )
        project_path = self.root / "typed-values.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = StudioController(
            self.app,
            QSettings(str(self.root / "typed-values-reopened.ini"), QSettings.Format.IniFormat),
        )
        self.assertTrue(reopened.open_project_path(project_path))
        reopened_id = reopened._active_source_id
        self.assertIsNotNone(reopened_id)
        self.assertEqual(
            reopened._project["data_sources"][0]["transform_steps"], steps,
        )
        self.assertEqual(
            [row["Value"] for row in reopened._loaded_candidates[reopened_id].rows],
            expected,
        )
        reopened.refresh_source()
        self.assertEqual(
            [row["Value"] for row in reopened._loaded_candidates[reopened_id].rows],
            expected,
        )

        source.write_text(
            '[{"Value":7,"Note":"ok"},{"Value":null,"Note":null},'
            '{"Value":"","Note":""}]',
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(
            [row["Value"] for row in reopened._loaded_candidates[reopened_id].rows],
            [7, None],
        )

    def test_transform_rejects_source_changed_after_preview(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Revenue\n12\n", encoding="utf-8")
        controller = self.controller()
        previewed = parse_file(source)
        self.assertTrue(controller._commit_import(source, previewed))
        steps = [{"op": "convert_type", "column": "Revenue", "type": "number"}]
        transformed = apply_transformations(previewed, steps)
        rows_before = copy.deepcopy(controller._rows)
        project_before = copy.deepcopy(controller._project)
        dirty_before = controller.dirty
        source.write_text("Revenue\n999\n", encoding="utf-8")

        self.assertFalse(controller._commit_transform_steps(
            controller._active_source_id,
            steps,
            transformed,
            previewed_source=previewed,
        ))

        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller.dirty, dirty_before)
        self.assertIn("source changed", controller.statusMessage)

    def test_recent_source_reopens_preview_and_cancel_preserves_active_data(self) -> None:
        active = self.root / "active.csv"
        recent = self.root / "recent.csv"
        active.write_text("Id\n1\n", encoding="utf-8")
        recent.write_text("Name;Value\nAda;12\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(active, parse_file(active)))
        controller._recent_source_store.add(
            recent, "csv", {"delimiter": ";", "encoding": "utf-8-sig", "has_header": True}
        )
        rows_before = copy.deepcopy(controller._rows)
        source_before = controller._active_source_path

        with patch.object(FileImportPreviewDialog, "exec", return_value=0):
            self.assertFalse(controller.openRecentSource(0))

        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller._active_source_path, source_before)
        self.assertEqual(controller.recentSources[0]["path"], str(recent.resolve()))

    def test_missing_recent_source_is_reported_without_replacing_loaded_data(self) -> None:
        active = self.root / "active.csv"
        missing = self.root / "missing.csv"
        active.write_text("Id\n1\n", encoding="utf-8")
        missing.write_text("Id\n2\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(active, parse_file(active)))
        controller._recent_source_store.add(missing, "csv")
        missing.unlink()
        rows_before = copy.deepcopy(controller._rows)

        self.assertFalse(controller.openRecentSource(0))

        self.assertEqual(controller._rows, rows_before)
        self.assertIn("missing", controller.statusMessage.casefold())
        self.assertFalse(controller.recentSources[0]["exists"])

    def test_export_active_transformed_table_to_csv_without_mutating_project(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_inline(
            parse_pasted_table("Name,Revenue\nAda,12\nLin,20", name="Sales")
        ))
        project_before = copy.deepcopy(controller._project)
        dirty_before = controller.dirty
        target = self.root / "exported.csv"

        self.assertTrue(controller.export_data_path(target))

        self.assertEqual(parse_file(target).headers, ["Name", "Revenue"])
        self.assertEqual(parse_file(target).rows, controller._rows)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller.dirty, dirty_before)

    def test_save_as_keeps_relative_links_inside_project_and_absolute_links_outside(self) -> None:
        source = self.root / "sales.csv"
        source.write_text("Revenue\n12\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        first_project = self.root / "first.npa"
        self.assertTrue(controller._save_to(first_project))
        self.assertEqual(controller._project["data_sources"][0]["path"], "sales.csv")

        second_project = self.root / "nested" / "second.npa"
        self.assertTrue(controller._save_to(second_project))
        self.assertEqual(
            controller._project["data_sources"][0]["path"], str(source.resolve())
        )
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(second_project))
        self.assertEqual(reopened._rows, [{"Revenue": "12"}])


if __name__ == "__main__":
    unittest.main()
