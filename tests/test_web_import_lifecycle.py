"""Acceptance checks for bounded anonymous Web table import."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
import ssl
import tempfile
import unittest
from decimal import Decimal
import zipfile
from urllib.error import URLError
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio import web_import
from analytics_studio.date_table_dialog import DateTableDialog
from analytics_studio.file_import import ImportCandidate
from analytics_studio.project import load_project
from analytics_studio.web_import import (
    WebImportError,
    WebPayload,
    discover_web_objects,
    parse_web_payload,
    validate_web_url,
)
from analytics_studio.web_import_dialog import WebImportDialog


URL = "https://data.example.test/metrics.json"


class WebImportLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def candidate(value: str) -> ImportCandidate:
        return ImportCandidate(
            "web",
            ["id", "amount"],
            [{"id": "1", "amount": value}],
            {"resource_type": "json", "json_path": ["data"]},
            [],
        )

    @staticmethod
    def _xlsx_bytes() -> bytes:
        workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'''
        relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''
        sheet = '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
 <row r="1"><c r="A1" t="inlineStr"><is><t>label</t></is></c></row>
 <row r="2"><c r="A2" t="inlineStr"><is><t>excel-row</t></is></c></row>
</sheetData></worksheet>'''
        data = BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/workbook.xml", workbook)
            archive.writestr("xl/_rels/workbook.xml.rels", relationships)
            archive.writestr("xl/worksheets/sheet1.xml", sheet)
        return data.getvalue()

    @staticmethod
    def _payload(url: str, media_type: str, body: bytes) -> WebPayload:
        return WebPayload(url, url, media_type, "utf-8", body)

    def test_html_json_csv_parsing_and_anonymous_https_rules(self) -> None:
        html = WebPayload(
            "https://data.example.test/page",
            "https://data.example.test/page",
            "text/html",
            "utf-8",
            b"<html><table><tr><th>Id</th><th>Label</th></tr>"
            b"<tr><td>1</td><td> Alpha </td></tr></table></html>",
        )
        html_objects = discover_web_objects(html)
        html_result = parse_web_payload(html, html_objects[0]["options"])
        self.assertEqual(html_result.rows, [{"Id": "1", "Label": "Alpha"}])

        json_payload = WebPayload(
            URL, URL, "application/json", "utf-8",
            b'{"data":[{"id":1,"amount":12.5,"note":null},{"id":2,"amount":20,"active":true}]}',
        )
        json_objects = discover_web_objects(json_payload)
        self.assertEqual(json_objects[0]["options"]["json_path"], ["data"])
        json_result = parse_web_payload(json_payload, json_objects[0]["options"])
        self.assertEqual(json_result.headers, ["id", "amount", "note", "active"])
        self.assertEqual(json_result.rows, [
            {"id": 1, "amount": Decimal("12.5"), "note": None, "active": None},
            {"id": 2, "amount": 20, "note": None, "active": True},
        ])

        csv_payload = WebPayload(
            "https://data.example.test/metrics.csv",
            "https://data.example.test/metrics.csv",
            "text/csv",
            "utf-8",
            b"Id;Amount\n1;10\n2;20\n",
        )
        csv_options = discover_web_objects(csv_payload)[0]["options"]
        csv_options.update({"delimiter": ";", "has_header": True})
        csv_result = parse_web_payload(csv_payload, csv_options)
        self.assertEqual(csv_result.rows, [
            {"Id": "1", "Amount": "10"}, {"Id": "2", "Amount": "20"}
        ])

        with self.assertRaisesRegex(WebImportError, "HTTPS"):
            validate_web_url("http://data.example.test/metrics.csv")
        with self.assertRaisesRegex(WebImportError, "embedded credentials"):
            validate_web_url("https://user:secret@data.example.test/metrics.csv")
        self.assertEqual(
            validate_web_url("https://data.example.test/metrics.csv?region=DXB"),
            "https://data.example.test/metrics.csv?region=DXB",
        )
        for secret_parameter in ("token", "access_token", "api_key", "X-Amz-Signature"):
            with self.subTest(secret_parameter=secret_parameter):
                with self.assertRaisesRegex(WebImportError, "token-like query parameters"):
                    validate_web_url(
                        f"https://data.example.test/metrics.csv?{secret_parameter}=secret"
                    )

    def test_xml_excel_and_parquet_web_resources_dispatch_to_local_readers(self) -> None:
        xml_payload = self._payload(
            "https://data.example.test/metrics.xml", "application/xml",
            b"<root><record><id>1</id><label>xml-row</label></record></root>",
        )
        xml_options = discover_web_objects(xml_payload)[0]["options"]
        xml_result = parse_web_payload(xml_payload, xml_options)
        self.assertEqual(xml_options, {"resource_type": "xml"})
        self.assertEqual(xml_result.kind, "web")
        self.assertEqual(xml_result.rows, [{"id": "1", "label": "xml-row"}])

        excel_payload = self._payload(
            "https://data.example.test/metrics.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            self._xlsx_bytes(),
        )
        excel_options = discover_web_objects(excel_payload)[0]["options"]
        excel_result = parse_web_payload(excel_payload, excel_options)
        self.assertEqual(excel_options, {"resource_type": "excel"})
        self.assertEqual(excel_result.rows, [{"label": "excel-row"}])

        import pyarrow as pa
        import pyarrow.parquet as parquet

        parquet_bytes = BytesIO()
        parquet.write_table(pa.Table.from_pylist([{"label": "parquet-row"}]), parquet_bytes)
        parquet_payload = self._payload(
            "https://data.example.test/metrics.parquet",
            "application/octet-stream", parquet_bytes.getvalue(),
        )
        parquet_options = discover_web_objects(parquet_payload)[0]["options"]
        parquet_result = parse_web_payload(parquet_payload, parquet_options)
        self.assertEqual(parquet_options, {"resource_type": "parquet"})
        self.assertEqual(parquet_result.rows, [{"label": "parquet-row"}])

    def test_json_and_html_discovery_and_parse_respect_table_depth_and_data_limits(self) -> None:
        two_tables = self._payload(
            "https://data.example.test/tables", "text/html",
            b"<table><tr><th>id</th></tr><tr><td>1</td></tr></table>"
            b"<table><tr><th>id</th></tr><tr><td>2</td></tr></table>",
        )
        with patch.object(web_import, "MAX_HTML_TABLES", 1):
            self.assertEqual(len(discover_web_objects(two_tables)), 1)

        deep_json = self._payload(
            URL, "application/json", b'{"a":{"b":[{"id":1}]}}'
        )
        with patch.object(web_import, "MAX_JSON_DEPTH", 1):
            with self.assertRaisesRegex(WebImportError, "no flat array"):
                discover_web_objects(deep_json)

        json_payload = self._payload(
            URL, "application/json",
            b'{"data":[{"id":1},{"id":2},{"id":3}]}',
        )
        options = discover_web_objects(json_payload)[0]["options"]
        preview = parse_web_payload(json_payload, options, row_limit=1)
        self.assertEqual(preview.rows, [{"id": 1}])
        self.assertTrue(any("capped at 1 rows" in item for item in preview.notices))
        with patch.object(web_import, "MAX_CELLS", 2):
            capped = parse_web_payload(json_payload, options)
        self.assertEqual(capped.rows, [{"id": 1}, {"id": 2}])
        self.assertTrue(any("capped at 2 rows" in item for item in capped.notices))

        two_columns = self._payload(
            URL, "application/json", b'{"data":[{"a":1,"b":2}]}'
        )
        options = discover_web_objects(two_columns)[0]["options"]
        with patch.object(web_import, "MAX_COLUMNS", 1):
            with self.assertRaisesRegex(WebImportError, "more than 1 columns"):
                parse_web_payload(two_columns, options)

        text_json = self._payload(
            URL, "application/json", b'{"data":[{"label":"four"}]}'
        )
        with patch.object(web_import, "MAX_SQLITE_TEXT_BYTES", 3):
            with self.assertRaisesRegex(WebImportError, "rendered-text limit"):
                parse_web_payload(text_json, discover_web_objects(text_json)[0]["options"])
        large_html = self._payload(
            "https://data.example.test/table", "text/html",
            b"<table><tr><th>value</th></tr><tr><td>four</td></tr></table>",
        )
        with patch.object(web_import, "MAX_SQLITE_TEXT_BYTES", 3):
            with self.assertRaisesRegex(WebImportError, "rendered-text limit"):
                parse_web_payload(large_html, discover_web_objects(large_html)[0]["options"])

    def test_fetch_limits_timeouts_tls_and_insecure_redirects(self) -> None:
        class Response:
            headers = {"Content-Type": "application/json; charset=utf-8"}

            def __init__(self, body, url=URL):
                self.body = body
                self.url = url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, limit):
                self.read_limit = limit
                return self.body[:limit]

            def geturl(self):
                return self.url

        class Opener:
            def __init__(self, response=None, error=None):
                self.response = response
                self.error = error
                self.timeout = None

            def open(self, request, timeout):
                self.timeout = timeout
                if self.error:
                    raise self.error
                return self.response

        with patch.object(web_import, "MAX_SOURCE_BYTES", 3):
            response = Response(b"1234")
            opener = Opener(response)
            with patch("analytics_studio.web_import.build_opener", return_value=opener):
                with self.assertRaisesRegex(WebImportError, "response exceeds"):
                    web_import.fetch_web_payload(URL)
            self.assertEqual(response.read_limit, 4)

        for error in (
            TimeoutError("read timed out"),
            URLError(ssl.SSLCertVerificationError("untrusted certificate")),
        ):
            opener = Opener(error=error)
            with self.subTest(error=type(error).__name__), patch(
                "analytics_studio.web_import.build_opener", return_value=opener
            ):
                with self.assertRaisesRegex(WebImportError, "Could not read the HTTPS source"):
                    web_import.fetch_web_payload(URL)
            self.assertEqual(opener.timeout, web_import.REQUEST_TIMEOUT_SECONDS)

        handler = web_import._HttpsOnlyRedirectHandler()
        request = web_import.Request(URL)
        destination = "http://data.example.test/redirected.csv"
        with self.assertRaisesRegex(WebImportError, "redirected to an insecure or invalid URL"):
            handler.redirect_request(request, None, 302, "Found", {}, destination)

        response = Response(b"{}", "https://data.example.test/redirected.csv?token=secret")
        with patch("analytics_studio.web_import.build_opener", return_value=Opener(response)):
            with self.assertRaisesRegex(WebImportError, "Could not read the HTTPS source"):
                web_import.fetch_web_payload(URL)

    def test_dialog_discovers_previews_and_accepts_selected_json_table(self) -> None:
        payload = WebPayload(
            URL, URL, "application/json", "utf-8",
            b'{"data":[{"id":1,"amount":10},{"id":2,"amount":20}]}',
        )
        dialog = WebImportDialog()
        dialog.url_edit.setText(URL)
        with (
            patch("analytics_studio.web_import_dialog.fetch_web_payload", return_value=payload),
            patch(
                "analytics_studio.web_import_dialog.read_web_source",
                side_effect=lambda connection, options: parse_web_payload(payload, options),
            ) as read_source,
        ):
            dialog._connect()
            self.assertEqual(dialog.object_combo.count(), 1)
            self.assertEqual(dialog.preview_model.rowCount(), 2)
            self.assertEqual(dialog.preview_model.columnCount(), 2)
            dialog._accept_import()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.url, URL)
        self.assertEqual(dialog.candidate.options["json_path"], ["data"])
        self.assertEqual(read_source.call_args.args[0], {"url": URL})
        dialog.deleteLater()

    def test_source_picker_dispatches_web_dialog_into_model_and_measure(self) -> None:
        controller = self.controller("settings.ini")
        payload = WebPayload(
            URL, URL, "application/json", "utf-8",
            b'{"data":[{"id":1,"amount":10},{"id":2,"amount":20}]}',
        )
        dialog = WebImportDialog()

        def accept_dialog() -> QDialog.DialogCode:
            dialog.url_edit.setText(URL)
            dialog._connect()
            self.assertEqual(dialog.preview_model.rowCount(), 2)
            dialog._accept_import()
            return QDialog.DialogCode.Accepted

        with (
            patch(
                "analytics_studio.controller.WebImportDialog",
                return_value=dialog,
            ),
            patch.object(dialog, "exec", side_effect=accept_dialog),
            patch(
                "analytics_studio.web_import_dialog.fetch_web_payload",
                return_value=payload,
            ),
            patch(
                "analytics_studio.web_import_dialog.read_web_source",
                side_effect=lambda connection, options: parse_web_payload(
                    payload, options
                ),
            ),
        ):
            self.assertTrue(
                controller.connectDataSource("other_web"),
                controller.statusMessage,
            )

        self.assertEqual(controller._active_source_kind, "web")
        self.assertEqual(controller._rows, [
            {"id": 1, "amount": 10},
            {"id": 2, "amount": 20},
        ])
        table = controller._model_table_for_source(
            controller._project, str(controller.activeTableId)
        )
        self.assertIsNotNone(table)
        self.assertEqual(table["column_types"]["amount"], "whole_number")
        table_name = str(table["name"])
        self.assertTrue(controller.create_measure(
            "Web picker total", f"SUM('{table_name}'[amount])"
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Web picker total"], "30")
        dialog.deleteLater()

    def test_pathless_url_source_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_web_import({"url": URL}, self.candidate("10")))
        source_id = controller.activeTableId
        table = controller._model_table_for_source(
            controller._project, str(source_id)
        )
        self.assertIsNotNone(table)
        table_name = str(table["name"])
        self.assertEqual(table["column_types"]["amount"], "whole_number")
        self.assertTrue(controller.create_measure(
            "Web total", f"SUM('{table_name}'[amount])"
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Web total"], "10")

        project_path = self.root / "web-project.npa"
        self.assertTrue(controller._save_to(project_path))
        saved_project, _ = load_project(project_path)
        saved_source = saved_project["data_sources"][0]
        self.assertEqual(saved_source["connection"], {"url": URL})
        self.assertEqual(saved_source["parser_options"], {
            "resource_type": "json", "json_path": ["data"]
        })

        reopened = self.controller("reopened-settings.ini")
        with patch(
            "analytics_studio.controller.read_web_source",
            side_effect=[self.candidate("20"), self.candidate("30")],
        ) as read_source:
            self.assertTrue(reopened.open_project_path(project_path))
            self.assertEqual(reopened._rows, [{"id": "1", "amount": "20"}])
            self.assertEqual(reopened.reportKpis["Web total"], "20")
            reopened.refresh_source()

        self.assertEqual(reopened._active_source_id, source_id)
        self.assertEqual(reopened._rows, [{"id": "1", "amount": "30"}])
        self.assertEqual(reopened.reportKpis["Web total"], "30")
        self.assertEqual(read_source.call_count, 2)
        self.assertEqual(read_source.call_args_list[0].args, (
            {"url": URL}, {"resource_type": "json", "json_path": ["data"]}
        ))

    def test_reimport_preserves_marked_date_table_and_typed_column(self) -> None:
        controller = self.controller("settings.ini")
        date_options = {"resource_type": "json", "json_path": ["data"]}
        initial = ImportCandidate(
            "web", ["Date", "label"],
            [
                {"Date": "2024-01-01", "label": "One"},
                {"Date": "2024-01-02", "label": "Two"},
            ], date_options, [],
        )
        self.assertTrue(controller._commit_web_import({"url": URL}, initial))
        with patch("analytics_studio.controller.read_web_source", return_value=initial):
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
            self.assertTrue(controller.mark_date_table_dialog(), controller.statusMessage)
        dialog.deleteLater()

        refreshed = ImportCandidate(
            "web", ["Date", "label"],
            [
                {"Date": "2024-02-01", "label": "New one"},
                {"Date": "2024-02-02", "label": "New two"},
            ], date_options, [],
        )
        self.assertTrue(controller._commit_web_import({"url": URL}, refreshed))

        table = controller._project["model"]["tables"][0]
        self.assertEqual(table["date_column"], "Date")
        self.assertEqual(table["column_types"]["Date"], "date")
        self.assertEqual(controller._rows[0]["Date"], "2024-02-01")


if __name__ == "__main__":
    unittest.main()
