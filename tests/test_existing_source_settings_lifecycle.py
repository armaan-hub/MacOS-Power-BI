"""Existing-source settings acceptance for local and pathless connectors."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyarrow as pa
import pyarrow.parquet as parquet
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.project import load_project
from analytics_studio.sql_server import SUPPORTED_DRIVERS
from analytics_studio.transformations import apply_transformations


SQL_CONNECTION = {
    "server": "old-sql.example.test",
    "port": 1433,
    "database": "Analytics",
    "username": "reader",
    "driver": SUPPORTED_DRIVERS[0],
    "encrypt": True,
}
SQL_OPTIONS = {
    "schema": "sales",
    "table_name": "orders",
    "object_type": "TABLE",
}
OLD_ODATA_ROOT = "https://old-api.example.test/odata/"
NEW_ODATA_ROOT = "https://new-api.example.test/odata/"
WEB_URL = "https://data.example.test/metrics.json"
NEW_WEB_URL = "https://data.example.test/updated-metrics.json"
TEXT_STEP = [{"op": "uppercase_text", "column": "label"}]


class ExistingSourceSettingsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(
            ["Existing source settings tests"]
        )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def _write_xlsx(path: Path, value: str) -> None:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets>
</workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        sheet = f'''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="inlineStr"><is><t>label</t></is></c></row>
 <row r="2"><c r="A2" t="inlineStr"><is><t>{value}</t></is></c></row>
</sheetData></worksheet>'''
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)

    @classmethod
    def _write_file_source(cls, path: Path, value: str) -> None:
        if path.suffix == ".xlsx":
            cls._write_xlsx(path, value)
        elif path.suffix == ".json":
            path.write_text(json.dumps([{"label": value}]), encoding="utf-8")
        elif path.suffix == ".xml":
            path.write_text(
                f"<root><record><label>{value}</label></record></root>",
                encoding="utf-8",
            )
        elif path.suffix == ".parquet":
            parquet.write_table(pa.Table.from_pylist([{"label": value}]), path)
        else:
            raise AssertionError(f"Unexpected test file type: {path.suffix}")

    @staticmethod
    def _candidate(kind: str, value: str, options: dict[str, object]) -> ImportCandidate:
        return ImportCandidate(kind, ["label"], [{"label": value}], options, [])

    def _accept_source_settings_in_editor(
        self,
        controller: StudioController,
        source_id: str,
    ) -> None:
        def accept(dialog: TransformDataDialog) -> QDialog.DialogCode:
            dialog.query_list.setCurrentRow(dialog._query_order.index(source_id))
            edit_button = dialog.findChild(
                QToolButton, "powerQueryEditSourceSettingsButton"
            )
            self.assertIsNotNone(edit_button)
            self.assertTrue(edit_button.isEnabled())
            edit_button.click()
            query = dialog._query_states[source_id]
            self.assertTrue(query.get("is_source_settings_changed"))
            dialog._accept_candidate()
            self.assertIsNotNone(dialog.accepted_queries)
            return QDialog.DialogCode.Accepted

        with patch.object(TransformDataDialog, "exec", new=accept):
            with patch.object(QMessageBox, "critical", return_value=QMessageBox.StandardButton.Ok):
                self.assertTrue(
                    controller.transform_data_dialog(), controller.statusMessage
                )

    def test_existing_excel_json_xml_and_parquet_settings_apply_reopen_and_refresh(self) -> None:
        cases = (
            ("excel", ".xlsx"),
            ("json", ".json"),
            ("xml", ".xml"),
            ("parquet", ".parquet"),
        )
        for kind, suffix in cases:
            with self.subTest(kind=kind):
                old_path = self.root / f"old-{kind}{suffix}"
                replacement_path = self.root / f"replacement-{kind}{suffix}"
                self._write_file_source(old_path, "initial")
                self._write_file_source(replacement_path, "replacement")
                controller = self.controller(f"{kind}-settings.ini")
                self.assertTrue(
                    controller._commit_import(old_path, parse_file(old_path)),
                    controller.statusMessage,
                )
                source_id = str(controller._active_source_id)
                raw = controller._raw_candidates[source_id]
                transformed = apply_transformations(raw, TEXT_STEP)
                self.assertTrue(
                    controller._commit_transform_steps(
                        source_id,
                        TEXT_STEP,
                        transformed,
                        previewed_source=raw,
                    ),
                    controller.statusMessage,
                )

                replacement = parse_file(replacement_path)
                preview_dialog = MagicMock()
                preview_dialog.exec.return_value = QDialog.DialogCode.Accepted
                preview_dialog.candidate = replacement
                with (
                    patch(
                        "analytics_studio.controller.QFileDialog.getOpenFileName",
                        return_value=(str(replacement_path), ""),
                    ) as file_picker,
                    patch(
                        "analytics_studio.import_preview_dialog.FileImportPreviewDialog",
                        return_value=preview_dialog,
                    ) as import_preview,
                ):
                    self._accept_source_settings_in_editor(controller, source_id)

                source_record = next(
                    source
                    for source in controller._project["data_sources"]
                    if source["id"] == source_id
                )
                self.assertEqual(source_record["path"], str(replacement_path.resolve()))
                self.assertEqual(source_record["kind"], kind)
                self.assertEqual(source_record["id"], source_id)
                self.assertEqual(source_record["parser_options"], replacement.options)
                self.assertEqual(
                    controller._loaded_candidates[source_id].rows,
                    [{"label": "REPLACEMENT"}],
                )
                file_picker.assert_called_once()
                import_preview.assert_called_once()
                self.assertTrue(import_preview.call_args.kwargs["source_editing"])

                project_path = self.root / f"{kind}-settings.npa"
                self.assertTrue(controller._save_to(project_path))
                reopened = self.controller(f"{kind}-reopened.ini")
                self.assertTrue(reopened.open_project_path(project_path))
                self.assertEqual(reopened.activeTableId, source_id)
                self.assertEqual(
                    reopened._loaded_candidates[source_id].rows,
                    [{"label": "REPLACEMENT"}],
                )
                self._write_file_source(replacement_path, "refreshed")
                reopened.refresh_source()
                self.assertEqual(
                    reopened._loaded_candidates[source_id].rows,
                    [{"label": "REFRESHED"}],
                )

    def test_existing_sql_server_odata_and_web_settings_apply_reopen_and_refresh(self) -> None:
        cases = ("sql_server", "odata", "web")
        for kind in cases:
            with self.subTest(kind=kind):
                controller = self.controller(f"{kind}-settings.ini")
                if kind == "sql_server":
                    initial_options = dict(SQL_OPTIONS)
                    initial = self._candidate(kind, "initial", initial_options)
                    with patch("analytics_studio.controller.set_sql_server_password"):
                        self.assertTrue(
                            controller._commit_sql_server_import(
                                SQL_CONNECTION, "old-secret", initial
                            ),
                            controller.statusMessage,
                        )
                    replacement_connection = {
                        **SQL_CONNECTION,
                        "server": "new-sql.example.test",
                    }
                    replacement_options = dict(SQL_OPTIONS)
                    replacement = self._candidate(
                        kind, "replacement", replacement_options
                    )
                    sql_dialog = MagicMock()
                    sql_dialog.exec.return_value = QDialog.DialogCode.Accepted
                    sql_dialog.candidate = replacement
                    sql_dialog.connection_settings = replacement_connection
                    sql_dialog.password = "new-secret"
                    dialog_patch = patch(
                        "analytics_studio.controller.SQLServerImportDialog",
                        return_value=sql_dialog,
                    )
                elif kind == "odata":
                    initial_options = {
                        "entity_set_name": "Metrics",
                        "entity_url": f"{OLD_ODATA_ROOT}Metrics",
                    }
                    initial = self._candidate(kind, "initial", initial_options)
                    self.assertTrue(
                        controller._commit_odata_import(
                            {"service_root": OLD_ODATA_ROOT}, initial
                        ),
                        controller.statusMessage,
                    )
                    replacement_options = {
                        "entity_set_name": "Metrics",
                        "entity_url": f"{NEW_ODATA_ROOT}Metrics",
                    }
                    replacement = self._candidate(
                        kind, "replacement", replacement_options
                    )
                    odata_dialog = MagicMock()
                    odata_dialog.exec.return_value = QDialog.DialogCode.Accepted
                    odata_dialog.candidate = replacement
                    odata_dialog.service_root = NEW_ODATA_ROOT
                    dialog_patch = patch(
                        "analytics_studio.controller.ODataFeedImportDialog",
                        return_value=odata_dialog,
                    )
                    replacement_connection = {"service_root": NEW_ODATA_ROOT}
                else:
                    initial_options = {
                        "resource_type": "json",
                        "json_path": ["data"],
                    }
                    initial = self._candidate(kind, "initial", initial_options)
                    self.assertTrue(
                        controller._commit_web_import({"url": WEB_URL}, initial),
                        controller.statusMessage,
                    )
                    replacement_options = dict(initial_options)
                    replacement = self._candidate(
                        kind, "replacement", replacement_options
                    )
                    web_dialog = MagicMock()
                    web_dialog.exec.return_value = QDialog.DialogCode.Accepted
                    web_dialog.candidate = replacement
                    web_dialog.url = NEW_WEB_URL
                    dialog_patch = patch(
                        "analytics_studio.controller.WebImportDialog",
                        return_value=web_dialog,
                    )
                    replacement_connection = {"url": NEW_WEB_URL}

                source_id = str(controller._active_source_id)
                original_source = next(
                    source
                    for source in controller._project["data_sources"]
                    if source["id"] == source_id
                )
                original_connection = dict(original_source["connection"])
                raw = controller._raw_candidates[source_id]
                transformed = apply_transformations(raw, TEXT_STEP)
                source_reader = {
                    "sql_server": "analytics_studio.controller.read_sql_server_object",
                    "odata": "analytics_studio.controller.read_odata_entity_set",
                    "web": "analytics_studio.controller.read_web_source",
                }[kind]
                with patch(source_reader, return_value=raw):
                    self.assertTrue(
                        controller._commit_transform_steps(
                            source_id,
                            TEXT_STEP,
                            transformed,
                            previewed_source=raw,
                        ),
                        controller.statusMessage,
                    )
                if kind == "sql_server":
                    credential_getter = patch(
                        "analytics_studio.controller.get_sql_server_password",
                        return_value="old-secret",
                    )
                else:
                    credential_getter = patch(
                        "analytics_studio.controller.get_sql_server_password",
                        return_value="unused-secret",
                    )

                with (
                    dialog_patch,
                    credential_getter,
                    patch(source_reader, side_effect=[initial, replacement]),
                    patch("analytics_studio.controller.set_sql_server_password") as save_password,
                    patch("analytics_studio.controller.delete_sql_server_password") as delete_password,
                ):
                    self._accept_source_settings_in_editor(controller, source_id)

                source_record = next(
                    source
                    for source in controller._project["data_sources"]
                    if source["id"] == source_id
                )
                self.assertEqual(source_record["connection"].get(
                    "service_root",
                    source_record["connection"].get("url", source_record["connection"].get("server")),
                ), replacement_connection.get(
                    "service_root",
                    replacement_connection.get("url", replacement_connection.get("server")),
                ))
                self.assertNotIn("_staged_password", source_record)
                self.assertEqual(source_record["parser_options"], replacement_options)
                if kind == "sql_server":
                    self.assertNotEqual(
                        source_record["connection"]["credential_ref"],
                        original_connection["credential_ref"],
                    )
                self.assertEqual(
                    controller._loaded_candidates[source_id].rows,
                    [{"label": "REPLACEMENT"}],
                )
                if kind == "sql_server":
                    save_password.assert_called_once_with(
                        source_record["connection"]["credential_ref"],
                        "new-secret",
                        source_record["connection"],
                    )
                    delete_password.assert_called_once_with(
                        original_connection["credential_ref"],
                        original_connection,
                    )

                project_path = self.root / f"{kind}-settings.npa"
                self.assertTrue(controller._save_to(project_path))
                saved_project, _ = load_project(project_path)
                saved_source = next(
                    source
                    for source in saved_project["data_sources"]
                    if source["id"] == source_id
                )
                self.assertEqual(saved_source["connection"], source_record["connection"])
                self.assertNotIn("password", saved_source.get("connection", {}))
                self.assertNotIn("new-secret", project_path.read_text(encoding="utf-8"))
                reopened = self.controller(f"{kind}-reopened.ini")
                refreshed = self._candidate(kind, "refreshed", replacement_options)
                read_patch_path = {
                    "sql_server": "analytics_studio.controller.read_sql_server_object",
                    "odata": "analytics_studio.controller.read_odata_entity_set",
                    "web": "analytics_studio.controller.read_web_source",
                }[kind]
                reads = patch(read_patch_path, side_effect=[replacement, refreshed])
                with (
                    reads as read_source,
                    patch(
                        "analytics_studio.controller.get_sql_server_password",
                        return_value="new-secret",
                    ),
                ):
                    self.assertTrue(reopened.open_project_path(project_path))
                    self.assertEqual(reopened.activeTableId, source_id)
                    self.assertEqual(
                        reopened._loaded_candidates[source_id].rows,
                        [{"label": "REPLACEMENT"}],
                    )
                    reopened.refresh_source()

                self.assertEqual(
                    reopened._loaded_candidates[source_id].rows,
                    [{"label": "REFRESHED"}],
                )
                self.assertEqual(read_source.call_count, 2)
                self.assertEqual(read_source.call_args_list[0].args[0], saved_source["connection"])
                self.assertEqual(read_source.call_args_list[0].args[1], replacement_options)


if __name__ == "__main__":
    unittest.main()
